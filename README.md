# Autonomous Sales Co-Pilot

Autonomous Sales Co-Pilot is a custom Odoo 19 module that turns CRM leads into AI-generated sales quotations automatically. It reads inbound RFQ text and PDF attachments, extracts requested products and quantities using NVIDIA AI, matches them to products in Odoo, creates a sale order, and posts a structured summary back into the lead and quotation chatter.

This project is designed for the BuildOdoo hackathon workflow and focuses on the core sales use case: reducing time from lead intake to quote creation.

## Features

- AI-assisted quotation generation from CRM leads
- PDF RFQ parsing using pypdf
- NVIDIA NIM integration using the z-ai/glm-5.3-flash model
- Strict JSON response handling for safe parsing
- Product matching by SKU, barcode, or name
- Automatic sales order creation
- Stock-aware summary with low-stock and reorder recommendation hints
- HTML summary posted to the lead and sale order chatter
- Settings page for saving and testing the NVIDIA API key
- Compatibility with older saved config values

## Project workflow

1. A sales user opens a CRM lead.
2. The lead may contain:
   - description text
   - title or subject
   - PDF attachments with customer RFQ content
3. The user clicks the AI Generate Quote button.
4. The module extracts all inquiry text and PDF content.
5. The content is sent to NVIDIA AI using the configured API key.
6. The AI is instructed to return a strict JSON object containing:
   - customer_name
   - customer_email
   - items[] with product_hint and quantity
7. The system parses the result and validates that the payload is in the expected format.
8. Matching Odoo products are resolved by default code, barcode, or product name.
9. A sales order is created with matching order lines.
10. The module checks stock status and provides a recommendation if stock is low or unavailable.
11. A summary is posted back to the CRM lead and the generated sale order in HTML format.

## Tech stack

- Odoo 19
- Python 3
- NVIDIA NIM / chat completions API
- pypdf
- Odoo CRM + Sales modules

## Module structure

- custom_addons/sale_ai_copilot/
  - __manifest__.py
  - __init__.py
  - models/
    - __init__.py
    - crm_lead.py
    - res_config_settings.py
  - security/
    - ir.model.access.csv
  - views/
    - crm_lead_views.xml
    - res_config_settings_views.xml

## Installation

1. Place the module in your Odoo custom addons path.
2. Ensure your Odoo instance includes the required modules:
   - crm
   - sale_management
   - stock
3. Install the Python dependency:

```bash
C:\Program Files\Odoo 19.0.20260714\python\python.exe -m pip install pypdf
```

If needed, install the NVIDIA client dependency as well:

```bash
C:\Program Files\Odoo 19.0.20260714\python\python.exe -m pip install google-genai
```

For the current final implementation, the project uses NVIDIA AI and the z-ai/glm-5.3-flash model.

## Configuration

1. Open Odoo.
2. Go to CRM > Settings.
3. Find the section: NVIDIA AI Sales Co-Pilot Integration.
4. Enter the NVIDIA API key.
5. Click Test NVIDIA API.
6. Save the settings.

Store the key in the module setting and do not commit secrets to Git.

## Usage

1. Create or open a CRM lead.
2. Add the lead description and/or attach an RFQ PDF.
3. Click AI Generate Quote.
4. Review the created sales quotation and the summary posted in the chatter.

## Example data

A sample RFQ flow can be created with product records such as:

- Laptop Pro 14
- USB-C Hub

The quote generation logic then tries to match those items and produce a proper sale order.

## Security notes

- Never commit API keys or `.env` files.
- Use Odoo settings or secure environment configuration for credentials.
- Keep logs and generated files out of version control.

## Current scope

This module currently focuses on:

- CRM lead to quote conversion
- AI product extraction from RFQ text and PDFs
- automatic sales order creation
- basic inventory-aware stock warnings
- summary communication in Odoo chatter

It is a strong MVP and hackathon-ready solution, but it is not a full enterprise procurement forecasting engine.

## Repository notes

Use a clean Git repo and avoid committing large Odoo runtime directories, database configuration files, or local secrets.

## License

This project is provided for educational and hackathon use. Please ensure you comply with the Odoo licensing and third-party service terms for the model/API you use.

## Authors

- Jaleel Ansari

## Contact

For questions or improvements, contact the repository owner or maintain the app in the local Odoo environment where it is installed.
