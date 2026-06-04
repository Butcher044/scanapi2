package dashboard

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"system-monitoring/internal/db"
	"time"
)

type Server struct {
	db   *db.DB
	addr string
	port int
	mux  *http.ServeMux
}

func New(database *db.DB, host string, port int) *Server {
	mux := http.NewServeMux()
	s := &Server{db: database, addr: host, port: port, mux: mux}

	// API routes
	mux.HandleFunc("/api/summary", s.cors(s.handleSummary))
	mux.HandleFunc("/api/stats", s.cors(s.handleStats))
	mux.HandleFunc("/api/changes", s.cors(s.handleChanges))
	mux.HandleFunc("/api/dynamics", s.cors(s.handleDynamics))
	mux.HandleFunc("/api/services", s.cors(s.handleServices))
	mux.HandleFunc("/api/methods", s.cors(s.handleMethods))
	mux.HandleFunc("/api/fields", s.cors(s.handleFields))

	// Static assets from React build
	mux.Handle("/assets/", http.FileServer(http.Dir("frontend/dist")))

	// SPA catch-all: все остальные пути отдают index.html
	mux.HandleFunc("/", s.handleSPA)

	return s
}

func (s *Server) Start() error {
	addr := fmt.Sprintf("%s:%d", s.addr, s.port)
	log.Printf("Dashboard: http://%s", addr)
	return http.ListenAndServe(addr, s.mux)
}

// cors добавляет CORS-заголовки для разработки
func (s *Server) cors(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next(w, r)
	}
}

// handleSPA отдаёт React SPA: сначала ищет статический файл, иначе index.html
func (s *Server) handleSPA(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/api/") {
		http.NotFound(w, r)
		return
	}

	// Try exact static file
	if r.URL.Path != "/" {
		fpath := filepath.Join("frontend", "dist", filepath.Clean(r.URL.Path))
		if info, err := os.Stat(fpath); err == nil && !info.IsDir() {
			http.ServeFile(w, r, fpath)
			return
		}
	}

	// SPA fallback
	index := filepath.Join("frontend", "dist", "index.html")
	if _, err := os.Stat(index); err == nil {
		http.ServeFile(w, r, index)
		return
	}

	// Fallback if no React build — minimal status page
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, `<!DOCTYPE html><html><body>
<h2>Bank API Monitor</h2>
<p>Frontend not built. Run <code>cd frontend && npm install && npm run build</code></p>
<p><a href="/api/summary">API /api/summary</a></p>
</body></html>`)
}

// ── API handlers ──────────────────────────────────────────────────────────────

func (s *Server) handleSummary(w http.ResponseWriter, r *http.Request) {
	summary, err := s.db.GetSummary(r.Context())
	if err != nil {
		jsonError(w, err)
		return
	}

	type bankJSON struct {
		Name     string `json:"name"`
		Label    string `json:"label"`
		Services int    `json:"services"`
		Methods  int    `json:"methods"`
	}
	type resp struct {
		Banks         []bankJSON `json:"banks"`
		TotalServices int        `json:"total_services"`
		TotalMethods  int        `json:"total_methods"`
		ChangesToday  int        `json:"changes_today"`
		ChangesWeek   int        `json:"changes_week"`
		ChangesTotal  int        `json:"changes_total"`
	}

	out := resp{
		TotalServices: summary.TotalServices,
		TotalMethods:  summary.TotalMethods,
		ChangesToday:  summary.ChangesToday,
		ChangesWeek:   summary.ChangesWeek,
		ChangesTotal:  summary.ChangesTotal,
	}
	for _, b := range summary.Banks {
		out.Banks = append(out.Banks, bankJSON{
			Name:     b.Bank,
			Label:    bankLabel(b.Bank),
			Services: b.ServiceCount,
			Methods:  b.MethodCount,
		})
	}

	jsonOK(w, out)
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	stats, err := s.db.GetStats(r.Context())
	if err != nil {
		jsonError(w, err)
		return
	}

	type bankJSON struct {
		Name     string `json:"name"`
		Label    string `json:"label"`
		Services int    `json:"services"`
		Methods  int    `json:"methods"`
	}
	banks := make([]bankJSON, len(stats))
	for i, st := range stats {
		banks[i] = bankJSON{Name: st.Bank, Label: bankLabel(st.Bank), Services: st.ServiceCount, Methods: st.MethodCount}
	}
	jsonOK(w, map[string]any{"banks": banks})
}

func (s *Server) handleChanges(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	bank := q.Get("bank")
	changeType := q.Get("type")
	changeAction := q.Get("action")

	limit := 50
	offset := 0
	if v := q.Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 500 {
			limit = n
		}
	}
	if v := q.Get("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			offset = n
		}
	}

	changes, total, err := s.db.GetChangesFiltered(r.Context(), bank, changeType, changeAction, limit, offset)
	if err != nil {
		jsonError(w, err)
		return
	}

	type changeJSON struct {
		ID         int    `json:"id"`
		Bank       string `json:"bank"`
		BankLabel  string `json:"bank_label"`
		Type       string `json:"type"`
		Action     string `json:"action"`
		Entity     string `json:"entity"`
		Path       string `json:"path"`
		OldValue   string `json:"old_value"`
		NewValue   string `json:"new_value"`
		URL        string `json:"url"`
		DetectedAt string `json:"detected_at"`
	}

	out := make([]changeJSON, 0, len(changes))
	for _, c := range changes {
		dt := "—"
		if c.DetectedAt != nil {
			if t, ok := c.DetectedAt.(time.Time); ok {
				dt = t.Format("2006-01-02 15:04")
			}
		}
		out = append(out, changeJSON{
			ID:         c.ID,
			Bank:       c.Bank,
			BankLabel:  bankLabel(c.Bank),
			Type:       c.ChangeType,
			Action:     c.ChangeAction,
			Entity:     c.EntityName,
			Path:       c.EntityPath,
			OldValue:   c.OldValue,
			NewValue:   c.NewValue,
			URL:        c.URL,
			DetectedAt: dt,
		})
	}

	jsonOK(w, map[string]any{"changes": out, "total": total, "limit": limit, "offset": offset})
}

func (s *Server) handleDynamics(w http.ResponseWriter, r *http.Request) {
	weeks := 12
	dynamics, err := s.db.GetWeeklyChanges(r.Context(), weeks)
	if err != nil {
		jsonError(w, err)
		return
	}

	type dynJSON struct {
		Week  string `json:"week"`
		Count int    `json:"count"`
		Bank  string `json:"bank"`
		Label string `json:"label"`
	}
	out := make([]dynJSON, 0, len(dynamics))
	for _, d := range dynamics {
		out = append(out, dynJSON{Week: d.Week, Count: d.Count, Bank: d.Bank, Label: bankLabel(d.Bank)})
	}
	jsonOK(w, map[string]any{"dynamics": out})
}

func (s *Server) handleServices(w http.ResponseWriter, r *http.Request) {
	bank := r.URL.Query().Get("bank")
	if bank == "" {
		http.Error(w, `{"error":"bank required"}`, http.StatusBadRequest)
		return
	}

	services, err := s.db.GetBankServices(r.Context(), bank)
	if err != nil {
		jsonError(w, err)
		return
	}

	type svcJSON struct {
		ID   int    `json:"id"`
		Name string `json:"name"`
		URL  string `json:"url"`
	}
	out := make([]svcJSON, len(services))
	for i, svc := range services {
		out[i] = svcJSON{ID: svc.ID, Name: svc.Name, URL: svc.URL}
	}
	jsonOK(w, map[string]any{"services": out})
}

func (s *Server) handleMethods(w http.ResponseWriter, r *http.Request) {
	idStr := r.URL.Query().Get("service_id")
	if idStr == "" {
		http.Error(w, `{"error":"service_id required"}`, http.StatusBadRequest)
		return
	}
	id, err := strconv.Atoi(idStr)
	if err != nil {
		http.Error(w, `{"error":"invalid service_id"}`, http.StatusBadRequest)
		return
	}

	methods, err := s.db.GetServiceMethods(r.Context(), id)
	if err != nil {
		jsonError(w, err)
		return
	}

	type methodJSON struct {
		ID         int    `json:"id"`
		Name       string `json:"name"`
		HTTPMethod string `json:"http_method"`
		Path       string `json:"path"`
		URL        string `json:"url"`
	}
	out := make([]methodJSON, len(methods))
	for i, m := range methods {
		out[i] = methodJSON{ID: m.ID, Name: m.Name, HTTPMethod: m.HTTPMethod, Path: m.Path, URL: m.URL}
	}
	jsonOK(w, map[string]any{"methods": out})
}

func (s *Server) handleFields(w http.ResponseWriter, r *http.Request) {
	idStr := r.URL.Query().Get("method_id")
	if idStr == "" {
		http.Error(w, `{"error":"method_id required"}`, http.StatusBadRequest)
		return
	}
	id, err := strconv.Atoi(idStr)
	if err != nil {
		http.Error(w, `{"error":"invalid method_id"}`, http.StatusBadRequest)
		return
	}

	fields, err := s.db.GetFields(r.Context(), id)
	if err != nil {
		jsonError(w, err)
		return
	}

	type fieldJSON struct {
		ID       int    `json:"id"`
		Name     string `json:"name"`
		Type     string `json:"type"`
		Required bool   `json:"required"`
	}
	out := make([]fieldJSON, len(fields))
	for i, f := range fields {
		out[i] = fieldJSON{ID: f.ID, Name: f.Name, Type: f.FieldType, Required: f.Required}
	}
	jsonOK(w, map[string]any{"fields": out})
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func bankLabel(bank string) string {
	labels := map[string]string{
		"tbank":    "Т-Банк",
		"alfabank": "Альфа-Банк",
		"sber":     "Сбер",
		"tochka":   "Точка",
	}
	if l, ok := labels[bank]; ok {
		return l
	}
	return bank
}

func jsonOK(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("json encode error: %v", err)
	}
}

func jsonError(w http.ResponseWriter, err error) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusInternalServerError)
	fmt.Fprintf(w, `{"error":%q}`, err.Error())
}
