package migrator

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

// Migrator отвечает за прогон миграций
type Migrator struct {
	db *sql.DB
}

// New создает новый мигратор из *sql.DB
func New(db *sql.DB) *Migrator {
	return &Migrator{db: db}
}

// Run выполняет миграции
func (m *Migrator) Run(ctx context.Context) error {
	// Получаем директорию с миграциями
	migrationsDir := os.Getenv("MIGRATIONS_DIR")
	if migrationsDir == "" {
		migrationsDir = "./migrations"
	}

	// Настраиваем goose
	goose.SetTableName("schema_migrations")
	goose.SetVerbose(true)
	goose.SetDialect("postgres")

	// Выполняем миграции
	if err := goose.UpContext(ctx, m.db, migrationsDir); err != nil {
		return fmt.Errorf("миграции не удались: %w", err)
	}

	log.Println("Миграции успешно выполнены")
	return nil
}

// Down откатывает миграции
func (m *Migrator) Down(ctx context.Context) error {
	migrationsDir := os.Getenv("MIGRATIONS_DIR")
	if migrationsDir == "" {
		migrationsDir = "./migrations"
	}

	goose.SetTableName("schema_migrations")
	goose.SetDialect("postgres")

	if err := goose.DownContext(ctx, m.db, migrationsDir); err != nil {
		return fmt.Errorf("откат миграций не удался: %w", err)
	}

	log.Println("Миграции откатаны")
	return nil
}
