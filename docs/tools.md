# MCP tools

Generated from the tool catalog by `scripts/build_tools_doc.py`; do not edit it by hand.

The server always offers `siigo_status` and every read tool. The write tools are listed
only while the **Write actions** switch is on (see [Write actions](usage.md#write-actions)),
and every write still needs your approval.

## Status

| Tool | What it does |
|---|---|
| `siigo_status` | The app version, whether Siigo credentials are set, and whether write actions are on. Never returns secrets. |

## Read tools (45)

| Tool | Title | Siigo API |
|---|---|---|
| `siigo_get_credit_note` | Get credit note | `GET /v1/credit-notes/{id}` |
| `siigo_get_credit_note_pdf` | Get credit note pdf | `GET /v1/credit-notes/{id}/pdf` |
| `siigo_get_customer` | Get customer | `GET /v1/customers/{id}` |
| `siigo_get_invoice` | Get invoice | `GET /v1/invoices/{id}` |
| `siigo_get_invoice_dian_errors` | Get invoice dian errors | `GET /v1/invoices/{id}/stamp/errors` |
| `siigo_get_invoice_pdf` | Get invoice pdf | `GET /v1/invoices/{id}/pdf` |
| `siigo_get_invoice_xml` | Get invoice xml | `GET /v1/invoices/{id}/xml` |
| `siigo_get_journal` | Get journal | `GET /v1/journals/{id}` |
| `siigo_get_payment_receipt` | Get payment receipt | `GET /v1/payment-receipts/{id}` |
| `siigo_get_product` | Get product | `GET /v1/products/{id}` |
| `siigo_get_purchase` | Get purchase | `GET /v1/purchases/{id}` |
| `siigo_get_quotation` | Get quotation | `GET /v1/quotations/{id}` |
| `siigo_get_support_document` | Get support document | `GET /v1/purchase-support-documents/{id}` |
| `siigo_get_trial_balance_by_third_party_report` | Get trial balance by third party report | `POST /v1/test-balance-report-by-thirdparty` |
| `siigo_get_trial_balance_report` | Get trial balance report | `POST /v1/test-balance-report` |
| `siigo_get_voucher` | Get voucher | `GET /v1/vouchers/{id}` |
| `siigo_list_account_groups` | List account groups | `GET /v1/account-groups` |
| `siigo_list_accounts_payable` | List accounts payable | `GET /v1/accounts-payable` |
| `siigo_list_cost_centers` | List cost centers | `GET /v1/cost-centers` |
| `siigo_list_credit_note_types` | List credit note types | `GET /v1/document-types` |
| `siigo_list_credit_notes` | List credit notes | `GET /v1/credit-notes` |
| `siigo_list_customers` | List customers | `GET /v1/customers` |
| `siigo_list_document_types` | List document types | `GET /v1/document-types` |
| `siigo_list_expenses` | List expenses | `GET /v1/expenses` |
| `siigo_list_fixed_assets` | List fixed assets | `GET /v1/fixed-assets` |
| `siigo_list_invoice_types` | List invoice types | `GET /v1/document-types` |
| `siigo_list_invoices` | List invoices | `GET /v1/invoices` |
| `siigo_list_journal_types` | List journal types | `GET /v1/document-types` |
| `siigo_list_journals` | List journals | `GET /v1/journals` |
| `siigo_list_misc_incomes` | List misc incomes | `GET /v1/misc-incomes` |
| `siigo_list_payment_receipt_types` | List payment receipt types | `GET /v1/document-types` |
| `siigo_list_payment_receipts` | List payment receipts | `GET /v1/payment-receipts` |
| `siigo_list_payment_types` | List payment types | `GET /v1/payment-types` |
| `siigo_list_price_lists` | List price lists | `GET /v1/price-lists` |
| `siigo_list_products` | List products | `GET /v1/products` |
| `siigo_list_purchase_types` | List purchase types | `GET /v1/document-types` |
| `siigo_list_quotation_types` | List quotation types | `GET /v1/document-types` |
| `siigo_list_quotations` | List quotations | `GET /v1/quotations` |
| `siigo_list_support_document_types` | List support document types | `GET /v1/document-types` |
| `siigo_list_taxes` | List taxes | `GET /v1/taxes` |
| `siigo_list_users` | List users | `GET /v1/users` |
| `siigo_list_voucher_types` | List voucher types | `GET /v1/document-types` |
| `siigo_list_vouchers` | List vouchers | `GET /v1/vouchers` |
| `siigo_list_warehouses` | List warehouses | `GET /v1/warehouses` |
| `siigo_list_webhooks` | List webhooks | `GET /v1/webhooks` |

## Write tools (9)

| Tool | Title | Siigo API |
|---|---|---|
| `siigo_create_credit_note` | Create credit note | `POST /v1/credit-notes` |
| `siigo_create_customer` | Create customer | `POST /v1/customers` |
| `siigo_create_invoice` | Create invoice | `POST /v1/invoices` |
| `siigo_create_journal` | Create journal | `POST /v1/journals` |
| `siigo_create_product` | Create product | `POST /v1/products` |
| `siigo_create_voucher` | Create voucher | `POST /v1/vouchers` |
| `siigo_create_voucher_misc_income` | Create voucher misc income | `POST /v1/vouchers` |
| `siigo_update_customer` | Update customer | `PUT /v1/customers/{id}` |
| `siigo_update_product` | Update product | `PUT /v1/products/{id}` |
