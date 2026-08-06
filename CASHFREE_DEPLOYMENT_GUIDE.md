# Subscription Deployment Instructions

Congratulations! The Cashfree subscription system code is fully integrated into Locklet Pro. Please follow these steps to securely deploy the backend components and configure Cashfree correctly.

### 1. Deploy Supabase Edge Functions

Run the following commands using the Supabase CLI at the root of your project:

```bash
supabase functions deploy create-cashfree-order
supabase functions deploy verify-payment
supabase functions deploy cashfree-webhook
```

### 2. Set Supabase Secrets

Your Edge Functions require access to Cashfree credentials and the Supabase Service Role key. Apply them via the CLI:

```bash
supabase secrets set CASHFREE_APP_ID="your_cashfree_app_id"
supabase secrets set CASHFREE_SECRET_KEY="your_cashfree_secret_key"
supabase secrets set CASHFREE_ENV="PROD" # Use "SANDBOX" for testing
supabase secrets set SUPABASE_URL="https://your-project-ref.supabase.co"
supabase secrets set SUPABASE_SERVICE_ROLE_KEY="your_service_role_key"
```

*Note: Ensure you are using the Service Role Key for `SUPABASE_SERVICE_ROLE_KEY` so that the functions can securely update user subscription records while bypassing Row-Level Security (RLS).*

### 3. Configure Cashfree Webhook

1. Log into your Cashfree Merchant Dashboard.
2. Navigate to **Developers** > **Webhooks**.
3. Add a new endpoint URL:
   `https://your-project-ref.supabase.co/functions/v1/cashfree-webhook`
4. Select the **PAYMENT_SUCCESS_WEBHOOK** event.
5. Save the configuration.

*Note: Cashfree will sign the webhook payload using your `CASHFREE_SECRET_KEY`. Our Edge Function `cashfree-webhook` strictly enforces HMAC-SHA256 signature verification.*

### 4. Build and Test the Android App

1. Sync your Gradle project to pull down the newly added `com.cashfree.pg:android-sdk:2.1.2` dependency.
2. Run the application.
3. Tap "Upgrade to Pro" to test the integration. Once you pay securely in the sandbox/prod environment, you will see the UI immediately react to reflect your premium status and provide a history log.
