# Security

## Infrastructure Security
Loomo's platform runs on **AWS** infrastructure with the following security controls:
- All servers operate within **Virtual Private Clouds (VPCs)** with network segmentation
- **Web Application Firewall (WAF)** protects against common web exploits (XSS, SQL injection, CSRF)
- **DDoS protection** via AWS Shield Standard on all public endpoints
- All infrastructure is provisioned through **Infrastructure as Code** with change tracking and audit trails

## Data Encryption
- **At rest**: AES-256 encryption for all stored data, including backups
- **In transit**: TLS 1.2+ for all data transmission between clients and Loomo servers
- **Key management**: Encryption keys are managed through AWS KMS with automatic quarterly rotation
- **Database encryption**: All database instances use encrypted storage volumes

## Authentication and Access Control
- **Password requirements**: Minimum 12 characters, must include uppercase, lowercase, number, and special character
- **Two-Factor Authentication (2FA)**: Available for all users, required for Admins and Owners on Business and Enterprise plans
- **SSO/SAML**: Available on Enterprise plans — supports SAML 2.0, OIDC, and Active Directory integration
- **Session management**: Sessions expire after **12 hours** of inactivity, or **24 hours** maximum duration
- **Account lockout**: 5 failed login attempts trigger a **15-minute lockout**

## Audit Logging
Enterprise customers have access to a comprehensive **Audit Log** that records:
- User login and logout events
- Permission and role changes
- Data exports and deletions
- Configuration changes (integrations, settings, billing)
- Admin actions (user provisioning, ownership transfer)

Audit logs are retained for **1 year** and can be exported as CSV or JSON. Audit logs are **read-only** and **tamper-evident** — entries cannot be modified or deleted by any user, including Owners.

## Penetration Testing
Loomo conducts **annual third-party penetration tests** performed by an independent security firm. Summary findings are available to Enterprise customers under NDA. Loomo also operates a private **bug bounty program** — responsible disclosure inquiries can be sent to security@loomo.ai.

## Vulnerability Management
- Critical vulnerabilities are patched within **24 hours** of identification
- High-severity vulnerabilities are patched within **7 days**
- All dependencies are scanned weekly using automated vulnerability scanners
- Security patches are deployed without downtime through rolling deployments

## Incident Response
In the event of a security incident:
1. Loomo's security team is alerted within **15 minutes** of detection
2. Affected systems are isolated and the incident is classified by severity
3. Affected customers are notified within **72 hours** of a confirmed breach
4. A post-incident report is published within **5 business days** of resolution

For full details on breach notification, see the **Data Privacy & Security** policy.

## Compliance
Loomo maintains the following certifications and compliance standards:
- **SOC 2 Type II** (Security, Availability, Confidentiality)
- **GDPR** compliance for all customers
- **ISO 27001** certification for information security management
- **CCPA** compliance for California residents

Enterprise customers can request audit reports and compliance documentation through their CSM or by contacting compliance@loomo.ai.

## Reporting Security Concerns
If you discover a security vulnerability or suspect unauthorized access to your account:
- **Urgent**: Call the Enterprise support line (24/7 for Enterprise customers)
- **Non-urgent**: Email **security@loomo.ai** with details of the concern
- Do **not** publicly disclose potential vulnerabilities before Loomo has had an opportunity to investigate and remediate
