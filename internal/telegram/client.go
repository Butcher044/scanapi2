package telegram

import (
	"context"
	"fmt"
	"log"

	"system-monitoring/internal/db"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// Client Telegram бота
type Client struct {
	bot *tgbotapi.BotAPI
	db  *db.DB
}

// NewClient создает новый клиент Telegram
func NewClient(token string, database *db.DB) (*Client, error) {
	bot, err := tgbotapi.NewBotAPI(token)
	if err != nil {
		return nil, err
	}

	// В режиме бота (неpolling) можно включить debug
	// bot.Debug = true

	log.Printf("Telegram бот авторизован как: %s", bot.Self.UserName)

	return &Client{
		bot: bot,
		db:  database,
	}, nil
}

// StartPolling запускает обработку обновлений
func (c *Client) StartPolling(ctx context.Context) error {
	u := tgbotapi.NewUpdate(0)
	u.Timeout = 60

	updates := c.bot.GetUpdatesChan(u)

	for {
		select {
		case <-ctx.Done():
			return nil
		case update := <-updates:
			c.handleUpdate(update)
		}
	}
}

func (c *Client) handleUpdate(update tgbotapi.Update) {
	if update.Message == nil {
		return
	}

	msg := tgbotapi.NewMessage(update.Message.Chat.ID, "")
	msg.ParseMode = "Markdown"

	switch update.Message.Command() {
	case "start":
		// Подписка на уведомления
		ctx := context.Background()
		if err := c.db.AddSubscriber(ctx, update.Message.Chat.ID, update.Message.From.UserName); err != nil {
			log.Printf("Ошибка добавления подписчика: %v", err)
			msg.Text = "Произошла ошибка при подписке. Попробуйте позже."
		} else {
			msg.Text = "Вы успешно подписались на уведомления об изменениях API банков!"
		}
	case "stop":
		// Отписка от уведомлений
		ctx := context.Background()
		if err := c.db.RemoveSubscriber(ctx, update.Message.Chat.ID); err != nil {
			log.Printf("Ошибка удаления подписчика: %v", err)
			msg.Text = "Произошла ошибка при отписке. Попробуйте позже."
		} else {
			msg.Text = "Вы отписались от уведомлений."
		}
	case "help":
		msg.Text = "Команды:\n/start - Подписаться на уведомления\n/stop - Отписаться от уведомлений\n/help - Показать справку"
	default:
		msg.Text = "Используйте /start для подписки или /help для справки."
	}

	if _, err := c.bot.Send(msg); err != nil {
		log.Printf("Ошибка отправки сообщения: %v", err)
	}
}

// Notify отправляет уведомление о изменении
func (c *Client) Notify(change db.Change) {
	// Формируем сообщение
	text := formatChangeMessage(change)

	ctx := context.Background()
	subscribers, err := c.db.GetSubscribers(ctx)
	if err != nil {
		log.Printf("Ошибка получения подписчиков: %v", err)
		return
	}

	for _, sub := range subscribers {
		msg := tgbotapi.NewMessage(sub.ChatID, text)
		msg.ParseMode = "Markdown"

		if _, err := c.bot.Send(msg); err != nil {
			log.Printf("Ошибка отправки подписчику %d: %v", sub.ChatID, err)
		}
	}
}

func formatChangeMessage(change db.Change) string {
	// BR-08: Сообщение содержит:
	// 1) Источник (какой банк)
	// 2) Категория изменения (сервис, метод, наполнение метода – поля)
	// 3) Тип изменения (добавление, удаление, Изменение)
	// 4) Краткое описание
	// 5) Ссылку на детали

	bankNames := map[string]string{
		"tbank":    "Т-Банк",
		"alfabank": "Альфа-Банк",
		"sber":     "Сбер",
		"tochka":   "Точка",
	}

	bankName := bankNames[change.Bank]
	if bankName == "" {
		bankName = change.Bank
	}

	var category string
	switch change.ChangeType {
	case "service":
		category = "Сервис"
	case "method":
		category = "Метод"
	case "field":
		category = "Наполнение метода"
	}

	var action string
	switch change.ChangeAction {
	case "added":
		action = "Добавлен"
	case "removed":
		action = "Удален"
	case "modified":
		action = "Изменен"
	}

	emoji := ""
	switch change.ChangeAction {
	case "added":
		emoji = "🟢"
	case "removed":
		emoji = "🔴"
	case "modified":
		emoji = "🟡"
	}

	message := fmt.Sprintf("%s *%s*%s\n", emoji, action, bankName)
	message += fmt.Sprintf("_Категория:_ %s\n", category)
	message += fmt.Sprintf("_Название:_ %s\n", change.EntityName)

	if change.OldValue != "" || change.NewValue != "" {
		message += "_Изменение:_\n"
		if change.OldValue != "" {
			message += fmt.Sprintf("Было: %s\n", change.OldValue)
		}
		if change.NewValue != "" {
			message += fmt.Sprintf("Стало: %s\n", change.NewValue)
		}
	}

	if change.URL != "" {
		message += fmt.Sprintf("\n[Ссылка на документацию](%s)", change.URL)
	}

	return message
}
