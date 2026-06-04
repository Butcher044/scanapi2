package parser

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strings"

	"system-monitoring/internal/model"

	"github.com/PuerkitoBio/goquery"
)

// TochkaParser парсер для банка Точка
type TochkaParser struct {
	client  *http.Client
	BaseURL string
}

func NewTochkaParser() *TochkaParser {
	return &TochkaParser{
		client:  &http.Client{},
		BaseURL: "https://developers.tochka.com",
	}
}

func (p *TochkaParser) Name() string {
	return "tochka"
}

// Все в методах – это сервисы, кроме introduction и Работа с вебхуками
func (p *TochkaParser) ParseServices(ctx context.Context) ([]model.Service, error) {
	// Основная страница с API
	mainURL := "https://developers.tochka.com/docs/tochka-api/"

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, mainURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to fetch %s: %d", mainURL, resp.StatusCode)
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil, err
	}

	var services []model.Service
	seen := make(map[string]bool)

	// Отладочный вывод
	allLinks := doc.Find("a[href]")
	log.Printf("[Tochka] Всего ссылок на странице: %d", allLinks.Length())

	// Ищем в боковой навигации - всё кроме introduction и Работа с вебхуками
	doc.Find("nav a[href], aside a[href], div[class*='side'] a[href], ul[class*='nav'] a[href], div[class*='menu'] a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())

		// Пропускаем пустые и короткие названия
		if text == "" || len(text) < 3 {
			return
		}

		lowerText := strings.ToLower(text)
		lowerHref := strings.ToLower(href)

		// Пропускаем introduction и вебхуки
		if strings.Contains(lowerText, "introduction") || strings.Contains(lowerText, "вебхук") ||
			strings.Contains(lowerHref, "introduction") || strings.Contains(lowerText, "работа с вебхуками") {
			return
		}

		// Пропускаем нерелевантные ссылки
		if strings.Contains(lowerHref, "about") || strings.Contains(lowerHref, "start") ||
			strings.Contains(lowerHref, "tutorial") || strings.Contains(lowerText, "введение") ||
			strings.Contains(lowerText, "начало") || strings.Contains(lowerText, "подключение") {
			return
		}

		// Проверяем, что это ссылка на раздел API (обычно /docs/)
		if !strings.Contains(href, "/docs/") && !strings.HasPrefix(href, "/") {
			return
		}

		// Пропускаем дубликаты
		if seen[text] {
			return
		}
		seen[text] = true

		url := href
		if !strings.HasPrefix(href, "http") {
			url = p.BaseURL + href
		}

		services = append(services, model.Service{
			Name: text,
			URL:  url,
		})
	})

	// Если не нашли в боковой навигации, пробуем по всем ссылкам
	if len(services) == 0 {
		doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			lowerText := strings.ToLower(text)
			lowerHref := strings.ToLower(href)

			// Пропускаем introduction и вебхуки
			if strings.Contains(lowerText, "introduction") || strings.Contains(lowerText, "вебхук") ||
				strings.Contains(lowerHref, "introduction") {
				return
			}

			if !strings.Contains(href, "/docs/") {
				return
			}

			if seen[text] {
				return
			}
			seen[text] = true

			url := href
			if !strings.HasPrefix(href, "http") {
				url = p.BaseURL + href
			}

			services = append(services, model.Service{
				Name: text,
				URL:  url,
			})
		})
	}

	// Fallback
	if len(services) == 0 {
		log.Printf("[Tochka] WARNING: Fallback - парсинг не работает!")
		services = []model.Service{
			{Name: "FALLBACK_SERVICE", URL: "https://developers.tochka.com/docs/tochka-api/"},
		}
	}

	log.Printf("[Tochka] Найдено сервисов: %d", len(services))
	return services, nil
}

func (p *TochkaParser) ParseMethods(ctx context.Context, serviceURL string) ([]model.Method, error) {
	log.Printf("[Tochka] Парсинг методов для: %s", serviceURL)

	// Сначала ищем OpenAPI spec на странице
	specURL, err := FindOpenAPISpecURL(ctx, p.client, serviceURL)
	if err != nil {
		log.Printf("[Tochka] Ошибка поиска spec: %v", err)
		return nil, err
	}

	log.Printf("[Tochka] Найден spec URL: %s", specURL)

	// Если нашли OpenAPI spec - парсим его
	if specURL != "" {
		methods, _, err := ParseOpenAPISpec(ctx, p.client, specURL)
		if err == nil && len(methods) > 0 {
			log.Printf("[Tochka] Найдено методов из OpenAPI: %d", len(methods))
			return methods, nil
		}
		log.Printf("[Tochka] Не удалось распарсить OpenAPI или методов 0: %v", err)
	}

	// Fallback: пробуем старый парсинг по HTML
	log.Printf("[Tochka] Пробуем HTML парсинг")
	return p.parseMethodsHTML(ctx, serviceURL)
}

// parseMethodsHTML парсит методы из боковой навигации
func (p *TochkaParser) parseMethodsHTML(ctx context.Context, serviceURL string) ([]model.Method, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, serviceURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to fetch %s: %d", serviceURL, resp.StatusCode)
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil, err
	}

	var methods []model.Method
	seen := make(map[string]bool)

	// Ссылки-исключения (не методы API, а статьи/разделы)
	excludePatterns := []string{
		"введение", "начало", "подключение", "терминология",
		"авторизация", "песочница", "обновления api", "коллекция",
		"как интегрировать", "работа с клиентами", "работа с платежами",
		"описание методов", "следующая страница", "предыдущая страница",
		"о сервисе", "работа с разрешениями", ".api",
	}

	// Методы в боковой навигации
	doc.Find("nav a[href], aside a[href], div[class*='side'] a[href], ul[class*='nav'] a[href], div[class*='menu'] a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())

		if text == "" || len(text) < 3 {
			return
		}

		lowerHref := strings.ToLower(href)
		lowerText := strings.ToLower(text)

		// Пропускаем нерелевантные ссылки
		if strings.Contains(lowerHref, "intro") || strings.Contains(lowerHref, "about") ||
			strings.Contains(lowerHref, "start") || strings.Contains(lowerHref, "tutorial") {
			return
		}

		// Пропускаем статьи и разделы (не методы API)
		isExcluded := false
		for _, pattern := range excludePatterns {
			if strings.Contains(lowerText, pattern) {
				isExcluded = true
				break
			}
		}
		if isExcluded {
			return
		}

		if seen[text] {
			return
		}
		seen[text] = true

		url := href
		if !strings.HasPrefix(href, "http") {
			url = p.BaseURL + href
		}

		// Определяем HTTP метод
		httpMethod := ""
		lowerUrl := strings.ToLower(url)
		if strings.Contains(lowerUrl, "create") || strings.Contains(lowerText, "создать") ||
			strings.Contains(lowerText, "добавить") || strings.Contains(lowerText, "инициализ") {
			httpMethod = "POST"
		} else if strings.Contains(lowerUrl, "delete") || strings.Contains(lowerText, "удалить") {
			httpMethod = "DELETE"
		} else if strings.Contains(lowerUrl, "update") || strings.Contains(lowerText, "обновить") {
			httpMethod = "PUT"
		} else if strings.Contains(lowerUrl, "get") || strings.Contains(lowerText, "получить") ||
			strings.Contains(lowerText, "список") || strings.Contains(lowerText, "запрос") ||
			strings.Contains(lowerText, "получить") {
			httpMethod = "GET"
		}

		methods = append(methods, model.Method{
			Name:       text,
			HTTPMethod: httpMethod,
			URL:        url,
		})
	})

	// Если не нашли, пробуем искать по всем ссылкам
	if len(methods) == 0 {
		doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			lowerHref := strings.ToLower(href)
			if strings.Contains(lowerHref, "intro") || strings.Contains(lowerHref, "about") ||
				strings.Contains(lowerHref, "start") || strings.Contains(lowerHref, "tutorial") {
				return
			}

			if seen[text] {
				return
			}
			seen[text] = true

			url := href
			if !strings.HasPrefix(href, "http") {
				url = p.BaseURL + href
			}

			methods = append(methods, model.Method{
				Name: text,
				URL:  url,
			})
		})
	}

	log.Printf("[Tochka] Найдено методов: %d", len(methods))
	return methods, nil
}

func (p *TochkaParser) ParseFields(ctx context.Context, methodURL string) ([]model.Field, error) {
	if methodURL == "" {
		return nil, nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, methodURL, nil)
	if err != nil {
		return nil, err
	}

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil, err
	}

	var fields []model.Field

	// Ищем секцию с ответами
	doc.Find("div[class*='response'], table, div[class*='schema'], pre").Each(func(i int, s *goquery.Selection) {
		text := s.Text()
		lines := strings.Split(text, "\n")

		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "{") || strings.HasPrefix(line, "[") {
				continue
			}

			parts := strings.SplitN(line, ":", 2)
			if len(parts) == 2 {
				fieldName := strings.TrimSpace(parts[0])
				fieldName = strings.Trim(fieldName, `",{}`)

				if fieldName != "" && !strings.Contains(fieldName, " ") {
					description := strings.TrimSpace(parts[1])
					required := strings.Contains(description, "required") ||
						strings.Contains(description, "Обязательное") ||
						strings.Contains(description, "обязательно")

					fields = append(fields, model.Field{
						Name:        fieldName,
						Required:    required,
						Description: description,
					})
				}
			}
		}
	})

	return fields, nil
}
