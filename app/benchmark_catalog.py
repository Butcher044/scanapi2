"""
What the benchmark compares: bank-neutral capabilities, not service names.

Banks name and slice the same thing differently ("Счета и выписки", "Работа с
выписками", "Выписки"), so each capability is recognised by:
  paths   — regex over method paths (lower-cased): the most reliable signal,
            a method counts when its path matches;
  names   — regex over service names (lower-cased): the whole service counts;
  exclude — regex; a path or a name that matches it never counts.

Entries of one group must stay next to each other (the UI renders one header
per group). Keys are stored in benchmark_overrides — rename one only together
with a data migration. After changing a rule, check the matrix and the
"unmatched" block on real data (GET /api/benchmark).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    key: str
    group: str
    title: str
    paths: str = ""
    names: str = ""
    exclude: str = ""


ACCOUNTS = "Счета и выписки"
PAYMENTS = "Платежи"
FX = "ВЭД и валюта"
SBP = "СБП и эквайринг"
STAFF = "Сотрудники и выплаты"
DEALS = "Сделки и номинальные счета"
FUNDING = "Размещение и кредиты"
DOCS = "Документы и подпись"
CLIENT = "Клиент и доступ"
OTHER = "Другие продукты"

CATALOG: tuple[Capability, ...] = (
    # ── Счета и выписки ──
    Capability(
        "accounts", ACCOUNTS, "Счета и остатки",
        paths=r"/(bank-)?accounts(/\{[^}]+\})?$|/accounts/\{[^}]+\}/balances$|/balances$|/client-info$",
        exclude=r"nominal-accounts|/knopka/|^/pp/|aisp-pe|/individual/",
    ),
    Capability(
        "statement", ACCOUNTS, "Выписка по счёту",
        paths=r"statement|account-operations|/transactions/mt940",
        names=r"выписк",
        exclude=r"digital-ruble|/credit/statement|bank-control-statements|/knopka/",
    ),
    Capability("webhooks", ACCOUNTS, "Вебхуки (уведомления о событиях)", paths=r"webhook", names=r"вебхук"),

    # ── Платежи ──
    Capability(
        "ruble_payment", PAYMENTS, "Рублёвое платёжное поручение",
        paths=r"^/(jp/v[12]/|v1/|api/v1/)payments?(/|$)|^/payment/v1\.0/",
        names=r"плат[её]жн\w* поручени|^платежи$|^работа с платежами$",
        exclude=r"валют|card-transfer|payment-registry",
    ),
    Capability(
        "payment_requests", PAYMENTS, "Платёжные требования и акцепт",
        paths=r"payment-requests|acceptance-advances|advance-acceptances",
        names=r"плат[её]жн\w* требовани|акцепт",
    ),

    # ── ВЭД и валюта ──
    Capability("currency_payment", FX, "Валютное платёжное поручение", paths=r"pay-doc-cur", names=r"валютн\w* плат"),
    Capability("currency_conversion", FX, "Конвертация валюты", paths=r"conv-currency|conversion", names=r"конвертац"),
    Capability(
        "currency_control", FX, "Валютный контроль",
        paths=r"currency/contracts|curr-control|currency-operation|bank-control-statements|confirmatory-documents",
        names=r"валютн\w* (контракт|контрол|операци)|подтверждающих документ",
    ),

    # ── СБП и эквайринг ──
    Capability(
        "sbp_qr", SBP, "СБП: приём оплаты по QR-коду",
        paths=r"/qrcs?(/|$)|qr-code|/qrc-status",
        names=r"сбп",
        exclude=r"b2b|b2c|для юл|платежи через сбп|ссылок через сбп",
    ),
    Capability(
        "sbp_b2b", SBP, "СБП B2B: оплата между компаниями",
        paths=r"b2b|payment-link",
        names=r"b2b|сбп для юл|ссылок через сбп",
    ),
    Capability(
        "sbp_payouts", SBP, "СБП B2C: выплаты физлицам",
        paths=r"paymentb2c|b2cpay",
        names=r"сбп b2c|платежи через сбп",
    ),
    Capability(
        "internet_acquiring", SBP, "Интернет-эквайринг",
        paths=r"(^|/)acquiring/|chargebacks",
        names=r"эквайринг",
        exclude=r"торгов",
    ),
    Capability("pos_acquiring", SBP, "Торговый эквайринг (терминалы)", paths=r"/tacq/", names=r"торгов\w* эквайринг"),
    Capability(
        "subscriptions", SBP, "Подписки и рекуррентные платежи",
        paths=r"subscriptions",
        names=r"подписк",
        exclude=r"/cards/|/individual/",
    ),

    # ── Сотрудники и выплаты ──
    Capability("payroll", STAFF, "Зарплатный проект", paths=r"salary|payroll", names=r"зарплат"),
    Capability("self_employed", STAFF, "Выплаты самозанятым", paths=r"self-?employed|^/semp/", names=r"самозанят",
               exclude=r"/individual/"),
    Capability("esop", STAFF, "Опционы для сотрудников (ESOP)", paths=r"/esop/", names=r"мотивац"),

    # ── Сделки и номинальные счета ──
    Capability(
        "nominal_accounts", DEALS, "Номинальные счета и безопасные сделки",
        paths=r"nominal-accounts|^/na/|smart-contracts",
        names=r"безопасн\w* сделк|номинальн",
    ),
    Capability("escrow", DEALS, "Эскроу-счета", paths=r"escrow", names=r"эскроу"),

    # ── Размещение и кредиты ──
    Capability(
        "deposits", FUNDING, "Депозиты и НСО",
        paths=r"deposit|overnight|minimum-balance|/placement/",
        names=r"депозит|овернайт|\bнсо\b",
        exclude=r"/reports/|aisp-pe",
    ),
    Capability(
        "business_loans", FUNDING, "Кредиты бизнесу",
        paths=r"^/loans/|credit-requests|credit-offers",
        names=r"кредит\w* для бизнеса|кредитные предложения$|заявка на кредит",
        exclude=r"^/pp/",
    ),
    Capability("guarantees", FUNDING, "Банковские гарантии", paths=r"bank-guarantees", names=r"гарант"),
    Capability("factoring", FUNDING, "Факторинг", paths=r"^/aff/", names=r"факторинг"),
    Capability(
        "pos_lending", FUNDING, "Покупка в кредит для клиентов партнёра",
        paths=r"/pos/|smart-loans|/offline/partners/",
        names=r"pos-кредит|покупку в кредит|оплата в кредит",
    ),

    # ── Документы и подпись ──
    Capability(
        "invoices", DOCS, "Выставление счетов на оплату",
        paths=r"(^|/)bills(/|$)|/invoice/send|/openapi/invoice/",
        names=r"выставлени\w* сч[её]т",
    ),
    Capability("closing_docs", DOCS, "Закрывающие документы", paths=r"closing-documents|providedservicesact",
               names=r"закрывающ"),
    Capability(
        "signature", DOCS, "Электронная подпись и сертификаты",
        paths=r"signature|/crypto|cert-requests",
        names=r"подпис(ь|и|ью|ей)\b|сертификат",
        exclude=r"digital-ruble",
    ),

    # ── Клиент и доступ ──
    Capability(
        "company_info", CLIENT, "Информация о компании",
        paths=r"customer-info|client-info|/company$|/customers(/\{[^}]+\})?$",
        names=r"информаци\w* о (компании|клиенте)|профиль организации|работа с клиентами",
    ),
    Capability(
        "auth", CLIENT, "Авторизация и согласия (OAuth / OpenID)",
        paths=r"oauth|oidc|consents|userinfo|user-info",
        names=r"авторизац|authorization|credentials flow|разрешени|согласия",
    ),
    Capability(
        "counterparty_check", CLIENT, "Проверка контрагентов",
        paths=r"sberrating|traffic-lights|contractors-audit",
        names=r"благонад|отч[её]ты по контрагент|безопасный бизнес",
    ),
    Capability(
        "delegated_id", CLIENT, "Делегированная идентификация",
        paths=r"delegated-identification|user-compliance",
        names=r"делегированн\w* идентификац",
    ),

    # ── Другие продукты ──
    Capability(
        "business_cards", OTHER, "Бизнес-карты",
        paths=r"^/api/v\d/(company/)?cards?(/|$)",
        names=r"бизнес-карт",
        exclude=r"привилеги",
    ),
    Capability("encashment", OTHER, "Инкассация", paths=r"encashment", names=r"инкассац"),
    Capability("digital_ruble", OTHER, "Цифровой рубль", paths=r"digital-ruble", names=r"цифров\w* рубл"),
    Capability("tax_deduction", OTHER, "Налоговые вычеты и 3-НДФЛ", paths=r"tax-deduction|ndfl",
               names=r"налогов\w* вычет|ндфл"),
)

KEYS: frozenset[str] = frozenset(c.key for c in CATALOG)
