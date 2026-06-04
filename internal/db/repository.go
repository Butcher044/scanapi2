package db

import (
	"context"
	"database/sql"
	"fmt"
	"strings"

	"system-monitoring/internal/config"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
)

type DB struct {
	pool *pgxpool.Pool
}

type Snapshot struct {
	ID        int
	Bank      string
	CreatedAt interface{}
}

type Service struct {
	ID         int
	SnapshotID int
	Name       string
	URL        string
}

type Method struct {
	ID          int
	ServiceID   int
	Name        string
	HTTPMethod  string
	Path        string
	URL         string
	Description string
}

type MethodWithService struct {
	ID          int
	ServiceID   int
	ServiceName string
	Name        string
	HTTPMethod  string
	Path        string
	URL         string
}

type Field struct {
	ID          int
	MethodID    int
	Name        string
	FieldType   string
	Required    bool
	Description string
}

type Change struct {
	ID           int
	SnapshotID   int
	Bank         string
	ChangeType   string
	ChangeAction string
	EntityName   string
	EntityPath   string
	OldValue     string
	NewValue     string
	URL          string
	DetectedAt   interface{}
}

type Subscriber struct {
	ID       int
	ChatID   int64
	Username string
}

type BankStats struct {
	Bank         string
	ServiceCount int
	MethodCount  int
}

type Summary struct {
	Banks         []BankStats
	TotalServices int
	TotalMethods  int
	ChangesToday  int
	ChangesWeek   int
	ChangesTotal  int
}

func New(cfg config.DatabaseConfig) (*DB, error) {
	dsn := fmt.Sprintf("postgres://%s:%s@%s:%d/%s?sslmode=%s",
		cfg.User, cfg.Password, cfg.Host, cfg.Port, cfg.DBName, cfg.SSLMode)

	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		return nil, err
	}

	if err := pool.Ping(context.Background()); err != nil {
		return nil, err
	}

	return &DB{pool: pool}, nil
}

func (db *DB) Close() {
	db.pool.Close()
}

func (db *DB) Pool() *pgxpool.Pool {
	return db.pool
}

func (db *DB) SQLDB() (*sql.DB, error) {
	dsn := fmt.Sprintf("postgres://%s:%s@%s:%d/%s?sslmode=%s",
		db.pool.Config().ConnConfig.Config.User,
		db.pool.Config().ConnConfig.Config.Password,
		db.pool.Config().ConnConfig.Config.Host,
		db.pool.Config().ConnConfig.Config.Port,
		db.pool.Config().ConnConfig.Config.Database,
		"disable")

	return sql.Open("pgx", dsn)
}

// ── Snapshot operations ───────────────────────────────────────────────────────

func (db *DB) CreateSnapshot(ctx context.Context, bank string) (int, error) {
	var id int
	err := db.pool.QueryRow(ctx,
		"INSERT INTO snapshots (bank) VALUES ($1) RETURNING id", bank).Scan(&id)
	return id, err
}

func (db *DB) GetLatestSnapshot(ctx context.Context, bank string) (*Snapshot, error) {
	var s Snapshot
	err := db.pool.QueryRow(ctx,
		`SELECT id, bank, created_at FROM snapshots
		 WHERE bank = $1 ORDER BY created_at DESC LIMIT 1`, bank).Scan(&s.ID, &s.Bank, &s.CreatedAt)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	return &s, err
}

func (db *DB) GetSnapshotsForCleanup(ctx context.Context, bank string, keep int) ([]int, error) {
	if keep < 1 {
		return nil, nil
	}
	rows, err := db.pool.Query(ctx,
		`SELECT id FROM snapshots WHERE bank = $1
		 ORDER BY created_at DESC OFFSET $2`, bank, keep)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var ids []int
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

func (db *DB) DeleteSnapshots(ctx context.Context, ids []int) error {
	if len(ids) == 0 {
		return nil
	}
	_, err := db.pool.Exec(ctx, `DELETE FROM snapshots WHERE id = ANY($1)`, ids)
	return err
}

// ── Service operations ────────────────────────────────────────────────────────

func (db *DB) CreateService(ctx context.Context, snapshotID int, name, url string) (int, error) {
	var id int
	err := db.pool.QueryRow(ctx,
		`INSERT INTO services (snapshot_id, name, url)
		 VALUES ($1, $2, $3) ON CONFLICT (snapshot_id, name) DO NOTHING
		 RETURNING id`, snapshotID, name, url).Scan(&id)
	if err == pgx.ErrNoRows {
		err = db.pool.QueryRow(ctx,
			`SELECT id FROM services WHERE snapshot_id = $1 AND name = $2`, snapshotID, name).Scan(&id)
	}
	return id, err
}

func (db *DB) GetServices(ctx context.Context, snapshotID int) ([]Service, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT id, snapshot_id, name, url FROM services WHERE snapshot_id = $1`, snapshotID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var services []Service
	for rows.Next() {
		var s Service
		if err := rows.Scan(&s.ID, &s.SnapshotID, &s.Name, &s.URL); err != nil {
			return nil, err
		}
		services = append(services, s)
	}
	return services, rows.Err()
}

func (db *DB) GetBankServices(ctx context.Context, bank string) ([]Service, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT s.id, s.snapshot_id, s.name, s.url
		 FROM services s
		 JOIN snapshots sn ON sn.id = s.snapshot_id
		 WHERE sn.bank = $1 AND sn.id = (SELECT MAX(id) FROM snapshots WHERE bank = $1)
		 ORDER BY s.name`, bank)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var services []Service
	for rows.Next() {
		var s Service
		if err := rows.Scan(&s.ID, &s.SnapshotID, &s.Name, &s.URL); err != nil {
			return nil, err
		}
		services = append(services, s)
	}
	return services, rows.Err()
}

// ── Method operations ─────────────────────────────────────────────────────────

func (db *DB) CreateMethod(ctx context.Context, serviceID int, name, httpMethod, url, description, path string) (int, error) {
	var id int
	err := db.pool.QueryRow(ctx,
		`INSERT INTO methods (service_id, name, http_method, url, description, path)
		 VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`, serviceID, name, httpMethod, url, description, path).Scan(&id)
	return id, err
}

func (db *DB) GetMethods(ctx context.Context, serviceID int) ([]Method, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT id, service_id, name, http_method, COALESCE(path,''), url, description
		 FROM methods WHERE service_id = $1`, serviceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var methods []Method
	for rows.Next() {
		var m Method
		if err := rows.Scan(&m.ID, &m.ServiceID, &m.Name, &m.HTTPMethod, &m.Path, &m.URL, &m.Description); err != nil {
			return nil, err
		}
		methods = append(methods, m)
	}
	return methods, rows.Err()
}

func (db *DB) GetServiceMethods(ctx context.Context, serviceID int) ([]Method, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT id, service_id, name, http_method, COALESCE(path,''), url, description
		 FROM methods WHERE service_id = $1 ORDER BY http_method, name`, serviceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var methods []Method
	for rows.Next() {
		var m Method
		if err := rows.Scan(&m.ID, &m.ServiceID, &m.Name, &m.HTTPMethod, &m.Path, &m.URL, &m.Description); err != nil {
			return nil, err
		}
		methods = append(methods, m)
	}
	return methods, rows.Err()
}

func (db *DB) GetAllMethodsForSnapshot(ctx context.Context, snapshotID int) ([]MethodWithService, error) {
	rows, err := db.pool.Query(ctx, `
		SELECT m.id, m.service_id, s.name AS service_name, m.name, m.http_method,
		       COALESCE(m.path, ''), m.url
		FROM methods m
		JOIN services s ON s.id = m.service_id
		WHERE s.snapshot_id = $1`, snapshotID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var result []MethodWithService
	for rows.Next() {
		var m MethodWithService
		if err := rows.Scan(&m.ID, &m.ServiceID, &m.ServiceName, &m.Name, &m.HTTPMethod, &m.Path, &m.URL); err != nil {
			return nil, err
		}
		result = append(result, m)
	}
	return result, rows.Err()
}

// ── Field operations ──────────────────────────────────────────────────────────

func (db *DB) CreateField(ctx context.Context, methodID int, name, fieldType string, required bool, description string) (int, error) {
	var id int
	err := db.pool.QueryRow(ctx,
		`INSERT INTO fields (method_id, name, field_type, required, description)
		 VALUES ($1, $2, $3, $4, $5) RETURNING id`, methodID, name, fieldType, required, description).Scan(&id)
	return id, err
}

func (db *DB) GetFields(ctx context.Context, methodID int) ([]Field, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT id, method_id, name, field_type, required, description FROM fields WHERE method_id = $1`, methodID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var fields []Field
	for rows.Next() {
		var f Field
		if err := rows.Scan(&f.ID, &f.MethodID, &f.Name, &f.FieldType, &f.Required, &f.Description); err != nil {
			return nil, err
		}
		fields = append(fields, f)
	}
	return fields, rows.Err()
}

// ── Change operations ─────────────────────────────────────────────────────────

func (db *DB) CreateChange(ctx context.Context, change Change) (int, error) {
	var id int
	err := db.pool.QueryRow(ctx,
		`INSERT INTO changes (snapshot_id, bank, change_type, change_action, entity_name, entity_path, old_value, new_value, url)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id`,
		change.SnapshotID, change.Bank, change.ChangeType, change.ChangeAction,
		change.EntityName, change.EntityPath, change.OldValue, change.NewValue, change.URL).Scan(&id)
	return id, err
}

func (db *DB) GetChanges(ctx context.Context, limit int) ([]Change, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT id, snapshot_id, bank, change_type, change_action, entity_name, entity_path,
		        COALESCE(old_value,''), COALESCE(new_value,''), COALESCE(url,''), detected_at
		 FROM changes ORDER BY detected_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanChanges(rows)
}

func (db *DB) GetChangesFiltered(ctx context.Context, bank, changeType, changeAction string, limit, offset int) ([]Change, int, error) {
	var conditions []string
	var args []any
	i := 1

	if bank != "" {
		conditions = append(conditions, fmt.Sprintf("bank = $%d", i))
		args = append(args, bank)
		i++
	}
	if changeType != "" {
		conditions = append(conditions, fmt.Sprintf("change_type = $%d", i))
		args = append(args, changeType)
		i++
	}
	if changeAction != "" {
		conditions = append(conditions, fmt.Sprintf("change_action = $%d", i))
		args = append(args, changeAction)
		i++
	}

	where := "1=1"
	if len(conditions) > 0 {
		where = strings.Join(conditions, " AND ")
	}

	// total count
	var total int
	countArgs := make([]any, len(args))
	copy(countArgs, args)
	if err := db.pool.QueryRow(ctx, fmt.Sprintf("SELECT COUNT(*) FROM changes WHERE %s", where), countArgs...).Scan(&total); err != nil {
		return nil, 0, err
	}

	// data
	args = append(args, limit, offset)
	query := fmt.Sprintf(`
		SELECT id, snapshot_id, bank, change_type, change_action, entity_name, entity_path,
		       COALESCE(old_value,''), COALESCE(new_value,''), COALESCE(url,''), detected_at
		FROM changes WHERE %s ORDER BY detected_at DESC LIMIT $%d OFFSET $%d`, where, i, i+1)

	rows, err := db.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	changes, err := scanChanges(rows)
	return changes, total, err
}

func scanChanges(rows pgx.Rows) ([]Change, error) {
	var changes []Change
	for rows.Next() {
		var c Change
		if err := rows.Scan(&c.ID, &c.SnapshotID, &c.Bank, &c.ChangeType, &c.ChangeAction,
			&c.EntityName, &c.EntityPath, &c.OldValue, &c.NewValue, &c.URL, &c.DetectedAt); err != nil {
			return nil, err
		}
		changes = append(changes, c)
	}
	return changes, rows.Err()
}

// ── Subscriber operations ─────────────────────────────────────────────────────

func (db *DB) AddSubscriber(ctx context.Context, chatID int64, username string) error {
	_, err := db.pool.Exec(ctx,
		`INSERT INTO telegram_subscribers (chat_id, username) VALUES ($1, $2)
		 ON CONFLICT (chat_id) DO NOTHING`, chatID, username)
	return err
}

func (db *DB) RemoveSubscriber(ctx context.Context, chatID int64) error {
	_, err := db.pool.Exec(ctx, `DELETE FROM telegram_subscribers WHERE chat_id = $1`, chatID)
	return err
}

func (db *DB) GetSubscribers(ctx context.Context) ([]Subscriber, error) {
	rows, err := db.pool.Query(ctx, `SELECT id, chat_id, username FROM telegram_subscribers`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var subs []Subscriber
	for rows.Next() {
		var s Subscriber
		if err := rows.Scan(&s.ID, &s.ChatID, &s.Username); err != nil {
			return nil, err
		}
		subs = append(subs, s)
	}
	return subs, rows.Err()
}

// ── Statistics ────────────────────────────────────────────────────────────────

func (db *DB) GetStats(ctx context.Context) ([]BankStats, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT s.bank,
		        COUNT(DISTINCT sv.id) AS service_count,
		        COUNT(DISTINCT m.id)  AS method_count
		 FROM snapshots s
		 LEFT JOIN services sv ON sv.snapshot_id = s.id
		 LEFT JOIN methods m  ON m.service_id = sv.id
		 WHERE s.id IN (SELECT MAX(id) FROM snapshots GROUP BY bank)
		 GROUP BY s.bank
		 ORDER BY s.bank`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var stats []BankStats
	for rows.Next() {
		var st BankStats
		if err := rows.Scan(&st.Bank, &st.ServiceCount, &st.MethodCount); err != nil {
			return nil, err
		}
		stats = append(stats, st)
	}
	return stats, rows.Err()
}

func (db *DB) GetSummary(ctx context.Context) (Summary, error) {
	stats, err := db.GetStats(ctx)
	if err != nil {
		return Summary{}, err
	}

	var totalSvcs, totalMethods int
	for _, s := range stats {
		totalSvcs += s.ServiceCount
		totalMethods += s.MethodCount
	}

	var today, week, total int
	db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM changes WHERE detected_at::date = CURRENT_DATE`).Scan(&today)
	db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM changes WHERE detected_at >= NOW() - INTERVAL '7 days'`).Scan(&week)
	db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM changes`).Scan(&total)

	return Summary{
		Banks:         stats,
		TotalServices: totalSvcs,
		TotalMethods:  totalMethods,
		ChangesToday:  today,
		ChangesWeek:   week,
		ChangesTotal:  total,
	}, nil
}

func (db *DB) GetWeeklyChanges(ctx context.Context, weeks int) ([]struct {
	Week  string
	Count int
	Bank  string
}, error) {
	rows, err := db.pool.Query(ctx,
		`SELECT TO_CHAR(DATE_TRUNC('week', detected_at), 'YYYY-MM-DD') AS week,
		        COUNT(*) AS count, bank
		 FROM changes
		 WHERE detected_at >= NOW() - ($1::int * INTERVAL '1 week')
		 GROUP BY week, bank
		 ORDER BY week`, weeks)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var result []struct {
		Week  string
		Count int
		Bank  string
	}
	for rows.Next() {
		var r struct {
			Week  string
			Count int
			Bank  string
		}
		if err := rows.Scan(&r.Week, &r.Count, &r.Bank); err != nil {
			return nil, err
		}
		result = append(result, r)
	}
	return result, rows.Err()
}
