# Service Level Agreement

## Uptime Guarantee by Plan
Loomo provides the following monthly uptime guarantees:
- **Pro**: **99.9%** uptime (approximately 43 minutes of allowed downtime per month)
- **Business**: **99.95%** uptime (approximately 22 minutes of allowed downtime per month)
- **Enterprise**: **99.99%** uptime (approximately 4.3 minutes of allowed downtime per month)

Uptime is measured on a calendar month basis using automated monitoring.

## Promotional Uptime Guarantee
A **2024 marketing promotion** has upgraded all paying tiers to a **99.99% uptime guarantee** until further notice. This promotional guarantee applies to all active paying customers during the promotion period and supersedes the standard per-plan uptime guarantees.

## Service Credit Calculation
If uptime falls below the applicable guarantee in any calendar month, affected customers are eligible for a Service Credit calculated as:

**Credit = ((Total Minutes in Month − Actual Uptime Minutes) / Total Minutes in Month) × Monthly Subscription Fee**

Service Credits are applied as a credit to the next invoice and do not expire. Credits are capped at **100% of the monthly subscription fee** for the affected month.

## How to File a Service Credit Claim
Service credit claims must be filed within **7 calendar days** of the end of the month in which the downtime occurred. Claims can be submitted through **Settings → Support → Service Credit Request** or by emailing sla@loomo.ai. Claims must include the date(s) and approximate time(s) of the downtime experienced.

## Downtime Exclusions
The following events are **excluded** from downtime calculations and do not count toward uptime guarantees:
- **Scheduled maintenance** — announced at least **48 hours** in advance via the Loomo Status Page and email notification
- **Force Majeure events** — natural disasters, acts of war, government actions, or other events beyond Loomo's reasonable control
- **Customer-caused outages** — issues resulting from customer configuration, third-party integrations, or customer network problems
- **Beta features** — any feature explicitly marked as "Beta" or "Preview" in the UI

## Scheduled Maintenance Windows
Loomo performs routine maintenance during a weekly **maintenance window** on Sundays from **2:00 AM – 6:00 AM CST**. Most maintenance is completed without downtime. When downtime is required, it is announced at least 48 hours in advance and typically lasts under 30 minutes.

## Status Page and Incident Communication
Real-time platform status is available at **status.loomo.ai**. During incidents, Loomo posts updates at minimum every **30 minutes** until resolution. Post-incident reports are published within **48 hours** of resolution for any incident lasting longer than 15 minutes.

## SLA for API Availability
The Loomo API follows the same uptime guarantees as the platform. API-specific rate limits are documented separately at docs.loomo.ai/api. API degradation (elevated latency above 2x baseline without full outage) is tracked separately and does not trigger Service Credits unless it results in request failures.
