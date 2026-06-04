package parser

import (
	"context"
	"log"
	"system-monitoring/internal/db"
	"system-monitoring/internal/model"
	"system-monitoring/internal/telegram"

	"golang.org/x/sync/errgroup"
)

// Engine движок парсинга
type Engine struct {
	db          *db.DB
	parsers     map[string]BankParser
	telegram    *telegram.Client
	pythonParser *PythonParser
	usePython   bool
}

// NewEngine создает новый движок парсинга
func NewEngine(database *db.DB, tgClient *telegram.Client) *Engine {
	parsers := make(map[string]BankParser)
	parsers["tbank"] = NewTBankParser()
	parsers["alfa"] = NewAlfaParser()
	parsers["sber"] = NewSberParser()
	parsers["tochka"] = NewTochkaParser()

	return &Engine{
		db:       database,
		parsers:  parsers,
		telegram: tgClient,
		usePython: false,
	}
}

// NewPythonEngine создает движок с Python-парсером
func NewPythonEngine(database *db.DB, tgClient *telegram.Client, scriptPath string) *Engine {
	pythonParser := NewPythonParserWithTelegram(database, scriptPath, tgClient)

	return &Engine{
		db:           database,
		parsers:      nil,
		telegram:     tgClient,
		pythonParser: pythonParser,
		usePython:    true,
	}
}

// ParseAll парсит все банки
func (e *Engine) ParseAll(ctx context.Context) error {
	// Используем Python-парсер если настроен
	if e.usePython && e.pythonParser != nil {
		log.Println("Запуск Python-парсера")
		return e.pythonParser.Run(ctx, nil)
	}

	for bankName, parser := range e.parsers {
		log.Printf("Начало парсинга банка: %s", bankName)
		if err := e.ParseBank(ctx, bankName, parser); err != nil {
			log.Printf("Ошибка парсинга банка %s: %v", bankName, err)
			continue
		}
		log.Printf("Завершен парсинг банка: %s", bankName)
	}
	return nil
}

// ParseBank парсит конкретный банк
func (e *Engine) ParseBank(ctx context.Context, bankName string, parser BankParser) error {
	log.Printf("[%s] Начало парсинга", bankName)

	// Создаем новый снапшот
	snapshotID, err := e.db.CreateSnapshot(ctx, bankName)
	if err != nil {
		return err
	}
	log.Printf("[%s] Создан снапшот #%d", bankName, snapshotID)

	// Получаем предыдущий снапшот для сравнения
	prevSnapshot, err := e.db.GetLatestSnapshot(ctx, bankName)
	if err != nil {
		return err
	}
	if prevSnapshot != nil {
		log.Printf("[%s] Предыдущий снапшот #%d", bankName, prevSnapshot.ID)
	} else {
		log.Printf("[%s] Нет предыдущего снапшота", bankName)
	}

	// Парсим сервисы
	log.Printf("[%s] Парсинг сервисов...", bankName)
	services, err := parser.ParseServices(ctx)
	if err != nil {
		return err
	}
	log.Printf("[%s] Найдено сервисов: %d", bankName, len(services))

	var serviceIDs = make(map[string]int)
	for _, svc := range services {
		serviceID, err := e.db.CreateService(ctx, snapshotID, svc.Name, svc.URL)
		if err != nil {
			log.Printf("Ошибка создания сервиса %s: %v", svc.Name, err)
			continue
		}
		serviceIDs[svc.Name] = serviceID
	}
	log.Printf("[%s] Сохранено сервисов: %d", bankName, len(serviceIDs))

	// Сравниваем сервисы с предыдущим снапшотом
	if prevSnapshot != nil {
		e.compareServices(ctx, snapshotID, bankName, prevSnapshot.ID, services)
	}

	// Параллельно парсим методы для каждого сервиса
	g := new(errgroup.Group)
	for _, svc := range services {
		svc := svc // capture for closure
		serviceID := serviceIDs[svc.Name]
		if serviceID == 0 {
			continue
		}

		g.Go(func() error {
			methods, err := parser.ParseMethods(ctx, svc.URL)
			if err != nil {
				log.Printf("Ошибка парсинга методов для %s: %v", svc.Name, err)
				return nil // не фатальная ошибка
			}
			log.Printf("[%s] %s: найдено методов: %d", bankName, svc.Name, len(methods))

			for _, method := range methods {
				methodID, err := e.db.CreateMethod(ctx, serviceID, method.Name, method.HTTPMethod, method.URL, method.Description, "")
				if err != nil {
					continue
				}

				// Парсим поля
				fields, err := parser.ParseFields(ctx, method.URL)
				if err != nil || len(fields) == 0 {
					continue
				}
				log.Printf("[%s] %s / %s: найдено полей: %d", bankName, svc.Name, method.Name, len(fields))

				for _, field := range fields {
					e.db.CreateField(ctx, methodID, field.Name, field.Type, field.Required, field.Description)
				}
			}

			// Сравниваем методы с предыдущим снапшотом
			if prevSnapshot != nil {
				e.compareMethods(ctx, snapshotID, bankName, prevSnapshot.ID, svc.Name, methods)
			}

			return nil
		})
	}

	if err := g.Wait(); err != nil {
		log.Printf("Ошибка при параллельном парсинге: %v", err)
	}

	// Очистка старых снапшотов (оставляем только n-1)
	e.cleanupOldSnapshots(ctx, bankName)

	log.Printf("[%s] Парсинг завершён", bankName)
	return nil
}

func (e *Engine) compareServices(ctx context.Context, snapshotID int, bankName string, prevSnapshotID int, currentServices []model.Service) {
	prevServices, err := e.db.GetServices(ctx, prevSnapshotID)
	if err != nil {
		return
	}

	prevServiceMap := make(map[string]bool)
	for _, s := range prevServices {
		prevServiceMap[s.Name] = true
	}

	// Проверяем новые сервисы
	for _, svc := range currentServices {
		if !prevServiceMap[svc.Name] {
			// Новый сервис добавлен
			change := db.Change{
				SnapshotID:  snapshotID,
				Bank:        bankName,
				ChangeType:  "service",
				ChangeAction: "added",
				EntityName:  svc.Name,
				EntityPath:  svc.Name,
				URL:         svc.URL,
			}
			e.db.CreateChange(ctx, change)
			if e.telegram != nil {
				e.telegram.Notify(change)
			}
		}
	}

	// Проверяем удаленные сервисы
	currentServiceMap := make(map[string]bool)
	for _, s := range currentServices {
		currentServiceMap[s.Name] = true
	}

	for _, prev := range prevServices {
		if !currentServiceMap[prev.Name] {
			// Сервис удален
			change := db.Change{
				SnapshotID:   snapshotID,
				Bank:         bankName,
				ChangeType:   "service",
				ChangeAction: "removed",
				EntityName:   prev.Name,
				EntityPath:   prev.Name,
				URL:          prev.URL,
			}
			e.db.CreateChange(ctx, change)
			if e.telegram != nil {
				e.telegram.Notify(change)
			}
		}
	}
}

func (e *Engine) compareMethods(ctx context.Context, snapshotID int, bankName string, prevSnapshotID int, serviceName string, currentMethods []model.Method) {
	// Получаем предыдущие методы для этого сервиса
	prevServices, err := e.db.GetServices(ctx, prevSnapshotID)
	if err != nil {
		return
	}

	var prevServiceID int
	for _, s := range prevServices {
		if s.Name == serviceName {
			prevServiceID = s.ID
			break
		}
	}

	if prevServiceID == 0 {
		return
	}

	prevMethods, err := e.db.GetMethods(ctx, prevServiceID)
	if err != nil {
		return
	}

	prevMethodMap := make(map[string]db.Method)
	for _, m := range prevMethods {
		prevMethodMap[m.Name] = m
	}

	// Проверяем новые методы
	for _, method := range currentMethods {
		if _, exists := prevMethodMap[method.Name]; !exists {
			change := db.Change{
				SnapshotID:   snapshotID,
				Bank:         bankName,
				ChangeType:   "method",
				ChangeAction: "added",
				EntityName:   method.Name,
				EntityPath:   serviceName + " / " + method.Name,
				URL:          method.URL,
			}
			e.db.CreateChange(ctx, change)
			if e.telegram != nil {
				e.telegram.Notify(change)
			}
		} else {
			// Метод существует - проверяем изменения полей
			prevMethod := prevMethodMap[method.Name]
			e.compareFields(ctx, snapshotID, bankName, prevMethod.ID, serviceName, method.Name, method.URL)
		}
	}

	// Проверяем удаленные методы
	currentMethodMap := make(map[string]bool)
	for _, m := range currentMethods {
		currentMethodMap[m.Name] = true
	}

	for _, prev := range prevMethods {
		if !currentMethodMap[prev.Name] {
			change := db.Change{
				SnapshotID:   snapshotID,
				Bank:         bankName,
				ChangeType:   "method",
				ChangeAction: "removed",
				EntityName:   prev.Name,
				EntityPath:   serviceName + " / " + prev.Name,
				URL:          prev.URL,
			}
			e.db.CreateChange(ctx, change)
			if e.telegram != nil {
				e.telegram.Notify(change)
			}
		}
	}
}

func (e *Engine) compareFields(ctx context.Context, snapshotID int, bankName string, prevMethodID int, serviceName, methodName, methodURL string) {
	prevFields, err := e.db.GetFields(ctx, prevMethodID)
	if err != nil {
		return
	}

	prevFieldMap := make(map[string]db.Field)
	for _, f := range prevFields {
		prevFieldMap[f.Name] = f
	}

	// Здесь нужно получить текущие поля из БД
	// Для упрощения - предполагаем что парсинг полей уже сохранен
	// В реальной реализации нужно получить метод ID из текущего снапшота
}

func (e *Engine) cleanupOldSnapshots(ctx context.Context, bankName string) {
	// Оставляем только 2 последних снапшота (текущий и предыдущий для сравнения)
	ids, err := e.db.GetSnapshotsForCleanup(ctx, bankName, 2)
	if err != nil {
		log.Printf("Ошибка получения снапшотов для удаления: %v", err)
		return
	}

	if len(ids) > 0 {
		if err := e.db.DeleteSnapshots(ctx, ids); err != nil {
			log.Printf("Ошибка удаления старых снапшотов: %v", err)
		}
	}
}