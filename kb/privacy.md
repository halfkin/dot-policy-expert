# Data Privacy & Security

## Data Encryption Standards
All customer data is encrypted at rest using **AES-256** encryption. Data in transit is encrypted using **TLS 1.2** or higher. Encryption keys are managed through a dedicated key management service and rotated quarterly.

## Compliance Certifications
Loomo maintains the following compliance certifications:
- **SOC 2 Type II** — audited annually, covering security, availability, and confidentiality
- **GDPR compliant** — for all customers, regardless of location
- **ISO 27001 certified** — information security management system

Audit reports are available to Enterprise customers under NDA upon request.

## Data Hosting and Residency
All customer data is hosted on **AWS** infrastructure in the **US-East-1 (Virginia)** region by default. Enterprise customers can request data residency in **EU-West-1 (Ireland)** or **AP-Southeast-1 (Singapore)** as part of their contract. Data residency requests must be made before account provisioning.

## Breach Notification
In the event of a confirmed data breach affecting customer data, Loomo will notify affected customers within **72 hours** of confirmation. Notifications include: the nature of the breach, the data affected, remediation steps taken, and recommended actions for affected customers. Loomo maintains a documented incident response plan reviewed quarterly.

## Right to Be Forgotten
Upon receiving a formal **"Right to Be Forgotten" (RTBF)** request, Loomo will purge all identifiable user data within **30 days**. RTBF requests must be submitted in writing to privacy@loomo.ai by the data subject or their authorized representative. A confirmation of deletion is provided upon completion.

## Account Deletion and Data Scrubbing
Accounts marked for deletion enter a **45-day soft-delete** period. During this time, data is preserved but inaccessible, and the deletion can be reversed. After the soft-delete period, **permanent data scrubbing** occurs — all data is irreversibly deleted from primary storage and backups within 30 additional days.

## Data Retention by Plan
Data retention periods differ by plan tier:
- **Pro**: Data retained for **1 year** after account cancellation or expiration
- **Business**: Data retained for **3 years** after account cancellation or expiration
- **Enterprise**: Data retained **indefinitely** until the customer requests deletion

Active accounts retain all data regardless of plan tier. These retention periods apply only after the account is no longer active.

## Data Export
All customers can export their data at any time through **Settings → Account → Export Data**. Exports are delivered as a ZIP file containing CSV and JSON files within **24 hours** of the request. Enterprise customers have access to the **Data Export API** for programmatic data extraction.

## Third-Party Subprocessors
Loomo uses the following third-party subprocessors for data handling:
- **AWS** — Infrastructure and hosting
- **Stripe** — Payment processing
- **Intercom** — Customer communication (Enterprise plans)
- **Datadog** — Application monitoring (no customer PII)

A full subprocessor list with DPA details is available at loomo.ai/subprocessors.

## Data Processing Agreement
A standard Data Processing Agreement (DPA) is available for all customers and can be executed electronically through **Settings → Compliance → DPA**. Enterprise customers may negotiate custom DPA terms as part of their contract.
