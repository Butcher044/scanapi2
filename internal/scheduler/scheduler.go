package scheduler

import (
	"context"
	"log"
	"strings"
	"system-monitoring/internal/parser"

	"github.com/robfig/cron/v3"
)

// Scheduler планировщик задач
type Scheduler struct {
	cron    *cron.Cron
	engine  *parser.Engine
	timeStr string
}

// New создает новый планировщик
func New(engine *parser.Engine, timeStr string) *Scheduler {
	return &Scheduler{
		cron:   cron.New(),
		engine: engine,
		timeStr: timeStr,
	}
}

// Start запускает планировщик
func (s *Scheduler) Start(ctx context.Context) error {
	// Формат "10:00" -> cron "0 10 * * *" (минуты часы день_месяца день_недели)
	parts := strings.Split(s.timeStr, ":")
	if len(parts) != 2 {
		return logAndReturnError("неверный формат времени: " + s.timeStr)
	}
	cronExpr := parts[1] + " " + parts[0] + " * * *"
	_, err := s.cron.AddFunc(cronExpr, func() {
		log.Printf("Запуск запланированного парсинга в %s", s.timeStr)
		if err := s.engine.ParseAll(ctx); err != nil {
			log.Printf("Ошибка запланированного парсинга: %v", err)
		}
	})

	if err != nil {
		return err
	}

	s.cron.Start()
	log.Printf("Планировщик запущен, парсинг в %s МСК", s.timeStr)
	return nil
}

// Stop останавливает планировщик
func (s *Scheduler) Stop() {
	ctx := s.cron.Stop()
	<-ctx.Done()
	log.Println("Планировщик остановлен")
}

// RunNow запускает парсинг немедленно
func (s *Scheduler) RunNow(ctx context.Context) error {
	log.Println("Запуск ручного парсинга")
	return s.engine.ParseAll(ctx)
}

// GetNextRun возвращает время следующего запуска
func (s *Scheduler) GetNextRun() string {
	entries := s.cron.Entries()
	if len(entries) == 0 {
		return "Не запланировано"
	}
	return entries[0].Next.Format("2006-01-02 15:04:05")
}

func logAndReturnError(msg string) error {
	log.Println(msg)
	return &schedulingError{msg}
}

type schedulingError struct {
	msg string
}

func (e *schedulingError) Error() string {
	return e.msg
}