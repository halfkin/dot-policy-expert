# Troubleshooting & Common Issues

## Login and Access Issues

### Cannot Log In — Password Reset
If you cannot log in, try resetting your password at **loomo.ai/reset-password**. A reset link will be sent to the email address associated with your account. Reset links expire after **1 hour**. If you don't receive the email, check your spam folder or contact support.

### Cannot Log In — Account Locked
Accounts are **temporarily locked after 5 consecutive failed login attempts** for security. The lockout lasts **15 minutes** and resets automatically. If you believe your account has been locked in error, contact support to have it manually unlocked.

### Cannot Log In — SSO/SAML Issues
If your organization uses SSO and you cannot log in, verify with your IT administrator that your SSO configuration is active and your user is provisioned. Common SSO issues include: expired SAML certificates, incorrect Assertion Consumer Service (ACS) URL, and user not assigned to the Loomo app in your identity provider. SSO is available on **Enterprise plans only**.

## Performance and Loading Issues

### Slow Page Loading
If Loomo pages are loading slowly:
1. Check **status.loomo.ai** for any ongoing incidents
2. Clear your browser cache and cookies for loomo.ai
3. Disable browser extensions (ad blockers can interfere with Loomo)
4. Try a different browser or incognito/private window
5. Check your internet connection speed — Loomo recommends at least **5 Mbps** for optimal performance

### Dashboard Not Loading
If your dashboard shows a blank screen or loading spinner:
- This is most commonly caused by browser extensions or outdated cached data
- Try hard-refreshing the page (**Ctrl+Shift+R** on Windows, **Cmd+Shift+R** on Mac)
- If the issue persists, clear your browser cache for loomo.ai and reload

## Export and Reporting Issues

### Data Export Not Completing
Data exports typically complete within **24 hours**. If your export has not completed:
- Check **Settings → Account → Export History** for the export status
- Large accounts (>100,000 records) may take up to **48 hours**
- If the export shows "Failed," retry the export — transient errors occasionally occur
- Contact support if the export fails repeatedly

### Report Showing Incorrect Data
If a report or dashboard shows unexpected data:
- Verify the date range and filters applied to the report
- Check if any filters are hidden or inherited from a saved view
- Reports reflect data at the time of generation — they are not real-time
- If the data discrepancy persists after verifying filters, contact support with the specific report and expected vs. actual values

## Notification Issues

### Not Receiving Email Notifications
If you are not receiving email notifications from Loomo:
- Check your **notification preferences** in **Settings → Notifications**
- Verify that Loomo emails are not being caught by your spam filter — add **notifications@loomo.ai** to your safe sender list
- If you use a corporate email system, ask your IT team to whitelist the loomo.ai domain
- Notification delivery can be delayed up to **5 minutes** during peak usage

### Too Many Notifications
To reduce notification volume:
- Customize per-channel and per-project notification settings in **Settings → Notifications**
- Use the **"Mute" option** on individual channels or projects you don't need real-time updates for
- Set **"Do Not Disturb" hours** in your notification preferences to pause non-critical notifications

## Integration Issues

### Slack Integration Not Syncing
If the Slack integration is not syncing messages:
- Re-authorize the integration in **Settings → Integrations → Slack**
- Ensure the Loomo app is installed in the correct Slack workspace
- Check that the linked Slack channels still exist and haven't been archived
- The Slack integration requires **Slack admin approval** — verify with your Slack workspace admin

### Jira Sync Errors
If Jira issues are not syncing to Loomo:
- Verify the Jira project key in the integration settings matches exactly
- Check that the Loomo service account has the necessary Jira permissions
- Jira sync runs every **5 minutes** — allow time for changes to propagate
- If sync errors persist, disconnect and reconnect the Jira integration

## Account and Billing Issues

### Unexpected Charges on Invoice
If you see unexpected charges:
- Check if seats were added mid-cycle (seat additions are prorated)
- Verify if a plan upgrade occurred (upgrades are charged immediately)
- Review your **Invoice History** in **Settings → Billing** for itemized details
- If the charge is unexplained, contact billing@loomo.ai within **60 days** for investigation

### Cannot Access Enterprise Features
If you are on an Enterprise plan but cannot access Enterprise features (SSO, API, Audit Log):
- Verify your plan in **Settings → Billing → Current Plan**
- Some Enterprise features require activation by your CSM — contact your CSM or support
- If you recently upgraded, features may take up to **1 hour** to activate
