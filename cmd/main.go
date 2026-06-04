package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"
	"system-monitoring/internal/config"
	"system-monitoring/internal/dashboard"
	"system-monitoring/internal/db"
	"system-monitoring/internal/migrator"
	"system-monitoring/internal/parser"
	"system-monitoring/internal/scheduler"
	"system-monitoring/internal/telegram"
)

func main() {
	configPath := flag.String("config", "config.yaml", "Path to config file")
	runNow := flag.Bool("now", false, "Run parsing immediately")
	flag.Parse()

	// Загрузка конфигурации
	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("Ошибка загрузки конфигурации: %v", err)
	}

	// Подключение к БД
	database, err := db.New(cfg.Database)
	if err != nil {
		log.Fatalf("Ошибка подключения к БД: %v", err)
	}
	defer database.Close()
	log.Println("Подключение к БД установлено")

	// Запуск миграций
	sqlDB, err := database.SQLDB()
	if err != nil {
		log.Fatalf("Ошибка получения SQLDB: %v", err)
	}
	defer sqlDB.Close()

	m := migrator.New(sqlDB)
	migrationCtx := context.Background()
	if err := m.Run(migrationCtx); err != nil {
		log.Fatalf("Ошибка миграций: %v", err)
	}

	// Инициализация Telegram бота
	var tgClient *telegram.Client
	if cfg.Telegram.BotToken != "" {
		tgClient, err = telegram.NewClient(cfg.Telegram.BotToken, database)
		if err != nil {
			log.Printf("Предупреждение: не удалось инициализировать Telegram бота: %v", err)
		} else {
			log.Println("Telegram бот инициализирован")
		}
	}

	// Инициализация движка парсинга
	var engine *parser.Engine
	if cfg.PythonParser.Enabled {
		log.Printf("Используется Python-парсер: %s", cfg.PythonParser.ScriptPath)
		engine = parser.NewPythonEngine(database, tgClient, cfg.PythonParser.ScriptPath)
	} else {
		log.Println("Используется Go-парсер")
		engine = parser.NewEngine(database, tgClient)
	}

	// Инициализация планировщика
	sched := scheduler.New(engine, cfg.Scheduler.Time)

	// Контекст с отменой (для долгих операций)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Запуск планировщика
	if err := sched.Start(ctx); err != nil {
		log.Fatalf("Ошибка запуска планировщика: %v", err)
	}

	// Запуск дашборда
	dash := dashboard.New(database, cfg.Dashboard.Host, cfg.Dashboard.Port)
	go func() {
		if err := dash.Start(); err != nil {
			log.Printf("Ошибка запуска дашборда: %v", err)
		}
	}()

	// Запуск Telegram бота в горутине
	if tgClient != nil {
		go func() {
			if err := tgClient.StartPolling(ctx); err != nil {
				log.Printf("Ошибка Telegram polling: %v", err)
			}
		}()
	}

	// Если указан флаг -now, запускаем парсинг сразу
	if *runNow {
		log.Println("Запуск парсинга по запросу...")
		if err := engine.ParseAll(ctx); err != nil {
			log.Printf("Ошибка парсинга: %v", err)
		}
	}

	// Ожидание сигнала для завершения
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	sig := <-sigChan
	log.Printf("Получен сигнал %v, завершение работы...", sig)
	cancel()
	sched.Stop()
	log.Println("Работа завершена")
}