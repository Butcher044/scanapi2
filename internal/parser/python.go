package parser

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"system-monitoring/internal/db"
	"system-monitoring/internal/model"
	"system-monitoring/internal/telegram"
	"time"
)

// PythonParser запускает Python-парсер и сохраняет результаты в БД
type PythonParser struct {
	db            *db.DB
	scriptPath    string
	snapshotsPath string
	telegram      *telegram.Client
}

func NewPythonParser(database *db.DB, scriptPath string) *PythonParser {
	return &PythonParser{
		db:            database,
		scriptPath:    scriptPath,
		snapshotsPath: filepath.Join(filepath.Dir(scriptPath), "snapshots"),
	}
}

func NewPythonParserWithTelegram(database *db.DB, scriptPath string, tgClient *telegram.Client) *PythonParser {
	return &PythonParser{
		db:            database,
		scriptPath:    scriptPath,
		snapshotsPath: filepath.Join(filepath.Dir(scriptPath), "snapshots"),
		telegram:      tgClient,
	}
}

type BankType string

const (
	BankTBank  BankType = "tbank"
	BankTochka BankType = "tochka"
	BankAlfa   BankType = "alfabank"
	BankSber   BankType = "sber"
)

// Run запускает парсинг указанных банков
func (p *PythonParser) Run(ctx context.Context, banks []BankType) error {
	if len(banks) == 0 {
		banks = []BankType{BankTBank, BankTochka, BankAlfa, BankSber}
	}

	bankArgs := []string{"--banks"}
	for _, b := range banks {
		bankArgs = append(bankArgs, string(b))
	}

	// Определяем путь к python — предпочитаем venv
	pythonCmd := p.findPython()

	args := append([]string{p.scriptPath}, bankArgs...)
	cmd := exec.CommandContext(ctx, pythonCmd, args...)
	cmd.Dir = filepath.Dir(p.scriptPath)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	// Передаём PYTHONPATH чтобы относительные импорты работали
	cmd.Env = append(os.Environ(), "PYTHONPATH="+filepath.Dir(p.scriptPath))

	fmt.Printf("Запуск Python-парсера: %s %v\n", pythonCmd, bankArgs)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("ошибка запуска парсера: %w", err)
	}

	return p.importToDatabase(ctx, banks)
}

// findPython возвращает путь к python-интерпретатору (venv > python3 > python)
func (p *PythonParser) findPython() string {
	candidates := []string{
		"/opt/venv/bin/python3",
		"/opt/venv/bin/python",
		"python3",
		"python",
	}
	for _, c := range candidates {
		if path, err := exec.LookPath(c); err == nil {
			return path
		}
		// Check absolute path directly
		if strings.HasPrefix(c, "/") {
			if _, err := os.Stat(c); err == nil {
				return c
			}
		}
	}
	return "python3"
}

// importToDatabase загружает снапшоты из JSON в БД и выявляет изменения
func (p *PythonParser) importToDatabase(ctx context.Context, banks []BankType) error {
	today := time.Now().Format("2006-01-02")

	for _, bank := range banks {
		snapPath := filepath.Join(p.snapshotsPath, today, fmt.Sprintf("%s.json", bank))

		data, err := os.ReadFile(snapPath)
		if err != nil {
			fmt.Printf("Файл не найден: %s\n", snapPath)
			continue
		}

		var snapshot model.ParseSnapshot
		if err := json.Unmarshal(data, &snapshot); err != nil {
			return fmt.Errorf("ошибка парсинга JSON %s: %w", bank, err)
		}

		snapshot.TotalServices = len(snapshot.Services)
		for _, methods := range snapshot.Services {
			snapshot.TotalMethods += len(methods)
		}

		if err := p.saveSnapshot(ctx, bank, &snapshot); err != nil {
			return fmt.Errorf("ошибка сохранения %s: %w", bank, err)
		}

		fmt.Printf("Сохранено: %s — %d сервисов, %d методов\n", bank, snapshot.TotalServices, snapshot.TotalMethods)
	}

	return nil
}

// saveSnapshot сохраняет снапшот в БД и выявляет изменения
func (p *PythonParser) saveSnapshot(ctx context.Context, bank BankType, snapshot *model.ParseSnapshot) error {
	prevSnapshot, err := p.db.GetLatestSnapshot(ctx, string(bank))
	if err != nil {
		fmt.Printf("Ошибка получения предыдущего снапшота: %v\n", err)
	}

	snapshotID, err := p.db.CreateSnapshot(ctx, string(bank))
	if err != nil {
		return fmt.Errorf("ошибка создания снапшота: %w", err)
	}

	// Карта сервисов предыдущего снапшота
	prevServices := make(map[string]bool)
	if prevSnapshot != nil {
		prevSvcs, err := p.db.GetServices(ctx, prevSnapshot.ID)
		if err == nil {
			for _, s := range prevSvcs {
				prevServices[s.Name] = true
			}
		}
	}

	// Сохраняем сервисы и методы
	for svcName, methods := range snapshot.Services {
		var svcURL string
		if len(methods) > 0 {
			svcURL = methods[0].URLOnPortal
		}

		serviceID, err := p.db.CreateService(ctx, snapshotID, svcName, svcURL)
		if err != nil {
			return fmt.Errorf("ошибка создания сервиса %s: %w", svcName, err)
		}

		if !prevServices[svcName] && prevSnapshot != nil {
			p.saveAndNotify(ctx, snapshotID, string(bank), "service", "added",
				svcName, svcName, svcURL, "", "")
		}

		for _, m := range methods {
			methodID, err := p.db.CreateMethod(ctx, serviceID, m.Summary, m.HTTPMethod, m.URLOnPortal, m.Description, m.Path)
			if err != nil {
				return fmt.Errorf("ошибка создания метода: %w", err)
			}

			for _, field := range m.Response200Fields {
				if _, err := p.db.CreateField(ctx, methodID, field, "string", false, ""); err != nil {
					fmt.Printf("Ошибка создания поля %s: %v\n", field, err)
				}
			}
		}
	}

	// Проверяем удалённые сервисы
	if prevSnapshot != nil {
		prevSvcs, err := p.db.GetServices(ctx, prevSnapshot.ID)
		if err == nil {
			for _, s := range prevSvcs {
				if _, exists := snapshot.Services[s.Name]; !exists {
					p.saveAndNotify(ctx, snapshotID, string(bank), "service", "removed",
						s.Name, s.Name, s.URL, "", "")
				}
			}
		}
	}

	// Сравниваем методы (по HTTP-метод + path)
	if prevSnapshot != nil {
		p.diffMethods(ctx, snapshotID, string(bank), prevSnapshot.ID)
	}

	// Очистка старых снапшотов (оставляем 7)
	ids, err := p.db.GetSnapshotsForCleanup(ctx, string(bank), 7)
	if err != nil {
		fmt.Printf("Ошибка получения старых снапшотов: %v\n", err)
	} else if len(ids) > 0 {
		if err := p.db.DeleteSnapshots(ctx, ids); err != nil {
			fmt.Printf("Ошибка удаления старых снапшотов: %v\n", err)
		}
	}

	return nil
}

// diffMethods сравнивает методы двух снапшотов и сохраняет изменения
func (p *PythonParser) diffMethods(ctx context.Context, newSnapshotID int, bank string, prevSnapshotID int) {
	prevMethods, err := p.db.GetAllMethodsForSnapshot(ctx, prevSnapshotID)
	if err != nil {
		fmt.Printf("Ошибка получения методов предыдущего снапшота: %v\n", err)
		return
	}
	newMethods, err := p.db.GetAllMethodsForSnapshot(ctx, newSnapshotID)
	if err != nil {
		fmt.Printf("Ошибка получения методов нового снапшота: %v\n", err)
		return
	}

	// Ключ: "HTTP_METHOD:path", пропускаем методы без path
	prevMap := make(map[string]db.MethodWithService)
	for _, m := range prevMethods {
		if m.Path != "" {
			prevMap[m.HTTPMethod+":"+m.Path] = m
		}
	}
	newMap := make(map[string]db.MethodWithService)
	for _, m := range newMethods {
		if m.Path != "" {
			newMap[m.HTTPMethod+":"+m.Path] = m
		}
	}

	// Добавленные методы
	for key, m := range newMap {
		if _, exists := prevMap[key]; !exists {
			entityName := fmt.Sprintf("%s %s", m.HTTPMethod, m.Path)
			entityPath := fmt.Sprintf("%s / %s %s", m.ServiceName, m.HTTPMethod, m.Path)
			p.saveAndNotify(ctx, newSnapshotID, bank, "method", "added",
				entityName, entityPath, m.URL, "", "")
		}
	}

	// Удалённые методы
	for key, m := range prevMap {
		if _, exists := newMap[key]; !exists {
			entityName := fmt.Sprintf("%s %s", m.HTTPMethod, m.Path)
			entityPath := fmt.Sprintf("%s / %s %s", m.ServiceName, m.HTTPMethod, m.Path)
			p.saveAndNotify(ctx, newSnapshotID, bank, "method", "removed",
				entityName, entityPath, m.URL, "", "")
		}
	}

	// Изменённые поля ответов
	for key, newM := range newMap {
		if prevM, exists := prevMap[key]; exists {
			oldFields := p.getFieldNames(ctx, prevM.ID)
			newFields := p.getFieldNames(ctx, newM.ID)
			added, removed := diffSets(oldFields, newFields)
			if len(added)+len(removed) > 0 {
				entityName := fmt.Sprintf("%s %s", newM.HTTPMethod, newM.Path)
				entityPath := fmt.Sprintf("%s / %s %s", newM.ServiceName, newM.HTTPMethod, newM.Path)
				oldVal := strings.Join(formatDiff("-", removed), ", ")
				newVal := strings.Join(formatDiff("+", added), ", ")
				p.saveAndNotify(ctx, newSnapshotID, bank, "field", "modified",
					entityName, entityPath, newM.URL, oldVal, newVal)
			}
		}
	}
}

func (p *PythonParser) getFieldNames(ctx context.Context, methodID int) []string {
	fields, err := p.db.GetFields(ctx, methodID)
	if err != nil {
		return nil
	}
	names := make([]string, len(fields))
	for i, f := range fields {
		names[i] = f.Name
	}
	return names
}

func diffSets(old, new []string) (added, removed []string) {
	oldSet := make(map[string]bool)
	for _, v := range old {
		oldSet[v] = true
	}
	newSet := make(map[string]bool)
	for _, v := range new {
		newSet[v] = true
	}
	for v := range newSet {
		if !oldSet[v] {
			added = append(added, v)
		}
	}
	for v := range oldSet {
		if !newSet[v] {
			removed = append(removed, v)
		}
	}
	return
}

func formatDiff(prefix string, items []string) []string {
	result := make([]string, len(items))
	for i, v := range items {
		result[i] = prefix + v
	}
	return result
}

// saveAndNotify сохраняет изменение в БД и отправляет уведомление в Telegram
func (p *PythonParser) saveAndNotify(ctx context.Context, snapshotID int, bank, changeType, action,
	entityName, entityPath, url, oldValue, newValue string) {

	change := db.Change{
		SnapshotID:   snapshotID,
		Bank:         bank,
		ChangeType:   changeType,
		ChangeAction: action,
		EntityName:   entityName,
		EntityPath:   entityPath,
		OldValue:     oldValue,
		NewValue:     newValue,
		URL:          url,
	}

	// Всегда сохраняем в БД
	if _, err := p.db.CreateChange(ctx, change); err != nil {
		fmt.Printf("Ошибка сохранения изменения: %v\n", err)
	}

	// Уведомляем через Telegram если настроен
	if p.telegram != nil {
		p.telegram.Notify(change)
	}
}
