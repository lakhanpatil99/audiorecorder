# LOCKLET-PRO — CASHFREE PAYMENT INTEGRATION FORENSIC AUDIT REPORT

**Role:** Senior Android, Supabase & Cashfree Payment Engineer  
**Project:** LockletPro Android App — Subscription Payment Module  
**Objective:** Full forensic diagnostic of the error: *"com.lockletpro is not enabled or approved. Please reach out to care@cashfree.com."*  
**Scope:** Read-only audit — no code modifications  
**Date:** 2026-06-14  

---

## A. Subscription Flow Diagram

```
User taps "Upgrade to Pro"
│
├── UI: SubscriptionScreen.kt (L131)
│   └── subscriptionViewModel.startSubscription(activity, planType)
│
├── ViewModel: SubscriptionViewModel.kt — startSubscription() (L50)
│   ├── Sets uiState = Loading
│   ├── Gets Firebase UID
│   └── Calls Supabase Edge Function
│
├── Supabase Call: supabase.functions.invoke("create-cashfree-order") (L68)
│   ├── Client: SupabaseClientProvider.kt — uses BuildConfig.SUPABASE_URL + SUPABASE_KEY
│   └── Sends body: { uid, planType }
│
├── Edge Function: create-cashfree-order/index.ts
│   ├── Reads CASHFREE_APP_ID, CASHFREE_SECRET_KEY, CASHFREE_ENV from Deno.env
│   ├── ENV check: "PROD" → api.cashfree.com, else → sandbox.cashfree.com (L36-39)
│   ├── Generates order_id: ORDER_{uid}_{timestamp}
│   ├── POST /pg/orders with x-api-version: 2023-08-01
│   └── Returns { payment_session_id, order_id }
│
├── ViewModel: SubscriptionViewModel.kt — launchCashfree() (L108)
│   ├── *** CRITICAL: Environment selected by BuildConfig.DEBUG ***
│   │   ├── DEBUG=true  → CFSession.Environment.SANDBOX
│   │   └── DEBUG=false → CFSession.Environment.PRODUCTION
│   ├── Builds CFSession with sessionId + orderId
│   ├── Builds CFDropCheckoutPayment
│   └── Calls CFPaymentGatewayService.getInstance().doPayment(activity, payment)
│
├── *** ERROR OCCURS HERE ***
│   └── Cashfree SDK returns: "com.lockletpro is not enabled or approved"
│
├── (If payment succeeded — not currently reached)
│   ├── MainActivity.kt — onPaymentVerify(orderId) (L136)
│   │   └── subscriptionViewModel.handlePaymentSuccess(orderId)
│   │       ├── Calls verify-payment Edge Function
│   │       ├── Falls back to polling UserRepository
│   │       └── Sets uiState = Success
│   │
│   ├── verify-payment/index.ts
│   │   ├── GET /pg/orders/{order_id} from Cashfree
│   │   ├── If PAID: updates users table + inserts subscriptions row
│   │   └── Returns { status: "SUCCESS" }
│   │
│   └── cashfree-webhook/index.ts (async backup)
│       ├── HMAC-SHA256 signature verification
│       ├── If PAYMENT_SUCCESS_WEBHOOK: updates users + inserts subscription
│       └── Returns 200 OK
│
└── (On payment failure)
    └── MainActivity.kt — onPaymentFailure(error, orderId) (L145)
        └── subscriptionViewModel.handlePaymentFailure(errorMsg) → uiState = Error
```

### Files & Classes Involved

| Step | File | Class/Function |
|------|------|----------------|
| UI Trigger | [SubscriptionScreen.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/subscription/SubscriptionScreen.kt#L129-L131) | `FreeTierView.onUpgradeClick` |
| Order Creation | [SubscriptionViewModel.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L50-L101) | `startSubscription()` |
| SDK Launch | [SubscriptionViewModel.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L108-L147) | `launchCashfree()` |
| Callback Registration | [MainActivity.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/MainActivity.kt#L63-L67) | `CFPaymentGatewayService.setCheckoutCallback` |
| Payment Success | [MainActivity.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/MainActivity.kt#L136-L143) | `onPaymentVerify()` |
| Payment Failure | [MainActivity.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/MainActivity.kt#L145-L153) | `onPaymentFailure()` |
| Success Handling | [SubscriptionViewModel.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L153-L187) | `handlePaymentSuccess()` |
| Polling Verification | [SubscriptionViewModel.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L204-L243) | `verifyPaymentWithPolling()` |
| Supabase Client | [SupabaseClientProvider.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/data/SupabaseClientProvider.kt) | `SupabaseClientProvider.client` |
| Create Order (Backend) | [create-cashfree-order/index.ts](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts) | `serve()` handler |
| Verify Payment (Backend) | [verify-payment/index.ts](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts) | `serve()` handler |
| Webhook (Backend) | [cashfree-webhook/index.ts](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/cashfree-webhook/index.ts) | `serve()` handler |
| User State Refresh | [UserRepository.kt](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/data/repository/UserRepository.kt#L59-L91) | `getCurrentUser()` |

---

## B. Working Components

| Component | Status | Evidence |
|-----------|--------|----------|
| **applicationId** | ✅ Correct | `com.lockletpro` in [build.gradle.kts](file:///d:/Antigravity%20Projects/tests/LockletPro/app/build.gradle.kts#L13), [google-services.json](file:///d:/Antigravity%20Projects/tests/LockletPro/app/google-services.json#L12), [AndroidManifest.xml](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/AndroidManifest.xml#L9) — all consistent |
| **Supabase Client Init** | ✅ Correct | Uses BuildConfig values, installs Functions, Postgrest, Storage |
| **Firebase Auth** | ✅ Correct | Initialized in Application class; UID retrieved in SubscriptionViewModel |
| **Supabase Edge Function call** | ✅ Correct | `supabase.functions.invoke("create-cashfree-order", body)` properly formed |
| **Edge Function: create-cashfree-order** | ✅ Structurally Correct | Reads env vars, builds order, POSTs to Cashfree API, returns session_id + order_id |
| **Edge Function: verify-payment** | ✅ Structurally Correct | Fetches order status, updates users table, inserts subscription record |
| **Edge Function: cashfree-webhook** | ✅ Structurally Correct | HMAC-SHA256 signature verification, idempotent upsert |
| **CFSession Builder** | ✅ Correct | Sets environment, paymentSessionID, orderId |
| **CFDropCheckoutPayment Builder** | ✅ Correct | Standard usage |
| **CFPaymentGatewayService callback** | ✅ Correct | Registered in `onCreate()`, implements `CFCheckoutResponseCallback` |
| **ProGuard Rules** | ✅ Correct | `-keep class com.cashfree.** { *; }` and SLF4J dontwarn |
| **Cashfree Maven Repo** | ✅ Correct | `maven("https://maven.cashfree.com/release")` in [settings.gradle.kts](file:///d:/Antigravity%20Projects/tests/LockletPro/settings.gradle.kts#L14) |
| **Cashfree SDK Dependency** | ✅ Present | `com.cashfree.pg:api:2.2.8`, `core:2.2.8`, `ui:2.2.8` |
| **Data Models** | ✅ Correct | SupabaseUser, SubscriptionHistory properly serialized |
| **SubscriptionScreen UI** | ✅ Correct | Plan selection, loading/verifying/error states handled |
| **Subscription History Screen** | ✅ Present | Separate screen for viewing past purchases |

---

## C. Broken Components

| Component | Status | Issue |
|-----------|--------|-------|
| **🔴 Environment Mismatch (SDK vs Backend)** | ❌ CRITICAL | SDK environment uses `BuildConfig.DEBUG`, backend uses `CASHFREE_ENV` secret — these are **independently controlled** and can diverge |
| **🔴 Cashfree Merchant Account Status** | ❌ CRITICAL | Error message `"com.lockletpro is not enabled or approved"` comes directly from Cashfree's servers, indicating the merchant account is not activated/approved for the `com.lockletpro` package name |
| **🟡 Signing Config** | ⚠️ MISSING | No `signingConfigs` block in [build.gradle.kts](file:///d:/Antigravity%20Projects/tests/LockletPro/app/build.gradle.kts#L35-L43) — release build type has no explicit signing configuration |
| **🟡 Network Security Config** | ⚠️ MISSING | No `android:networkSecurityConfig` in manifest; not strictly required but recommended |
| **🟡 x-api-version inconsistency** | ⚠️ MISMATCH | create-cashfree-order uses `2023-08-01`, verify-payment uses `2022-09-01` |
| **🟡 Deep Links** | ⚠️ MISSING | No deep link intent filter for Cashfree payment redirects in manifest |

---

## D. High-Risk Issues

### 🔴 ISSUE #1: ENVIRONMENT SPLIT (CRITICAL — ROOT CAUSE)

**Location:** [SubscriptionViewModel.kt:L116-L120](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L116-L120) and [create-cashfree-order/index.ts:L5,L36-L39](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L5)

```
Android SDK Side:                      Supabase Backend Side:
┌──────────────────────┐               ┌──────────────────────────────┐
│ if (BuildConfig.DEBUG)│               │ CASHFREE_ENV secret          │
│   → SANDBOX          │               │   "PROD" → api.cashfree.com │
│ else                 │               │   else   → sandbox           │
│   → PRODUCTION       │               │   DEFAULT: "TEST"            │
└──────────────────────┘               └──────────────────────────────┘
```

> [!CAUTION]
> **The SDK environment and the backend API URL are controlled by TWO DIFFERENT VARIABLES that are NEVER synchronized.**  
> - A **release APK** (DEBUG=false) sets SDK to `PRODUCTION` but the backend may still have `CASHFREE_ENV=TEST` (the default fallback), which creates orders on `sandbox.cashfree.com`.
> - A **sandbox order** (created on sandbox.cashfree.com) **cannot be opened** by the SDK in `PRODUCTION` mode — and vice versa.
> - This cross-environment mismatch causes the Cashfree SDK to fail with the "not enabled or approved" error because the payment_session_id from one environment is invalid in the other.

**Additional fallback risk:** The `create-cashfree-order` function defaults to `"TEST"` if `CASHFREE_ENV` is not set:
```typescript
const ENV = Deno.env.get("CASHFREE_ENV") || "TEST";  // DEFAULT IS "TEST"
```
But the env check is `ENV === "PROD"`, meaning **any value other than exactly `"PROD"`** (including `"TEST"`, `"SANDBOX"`, `"production"`, or undefined) routes to the sandbox API.

### 🔴 ISSUE #2: CASHFREE MERCHANT ACCOUNT NOT APPROVED FOR PRODUCTION

**Evidence:** The error message `"com.lockletpro is not enabled or approved"` is a Cashfree **server-side error** returned when:
1. The merchant account has not completed KYC/activation for production payments
2. The package name `com.lockletpro` has not been whitelisted/registered in the Cashfree dashboard
3. The app ID (merchant ID) used in the API credentials doesn't have the `com.lockletpro` package approved

This is **NOT a code bug** — it's a Cashfree dashboard configuration issue. The Cashfree merchant account must have `com.lockletpro` explicitly registered and approved as an allowed Android package name.

### 🟡 ISSUE #3: NO SIGNING CONFIG IN GRADLE

**Location:** [build.gradle.kts:L35-L43](file:///d:/Antigravity%20Projects/tests/LockletPro/app/build.gradle.kts#L35-L43)

The release build type has no `signingConfig`:
```kotlin
release {
    isMinifyEnabled = true
    proguardFiles(...)
    // NO signingConfig = signingConfigs.getByName("release")
}
```

This means the release build is likely signed with Android Studio's auto-generated debug keystore or manually via command line. Cashfree may validate the signing certificate hash against registered values, and an inconsistent signing key would cause approval failures.

### 🟡 ISSUE #4: x-api-version MISMATCH BETWEEN FUNCTIONS

| Function | x-api-version |
|----------|---------------|
| [create-cashfree-order](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L45) | `2023-08-01` |
| [verify-payment](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L36) | `2022-09-01` |

Using different API versions across functions could lead to subtle differences in request/response schemas. This is a minor risk but indicates inconsistent setup.

### 🟡 ISSUE #5: HARDCODED DUMMY CUSTOMER PHONE

**Location:** [create-cashfree-order/index.ts:L55](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L55)

```typescript
customer_phone: "9999999999",
```

Cashfree may reject orders in production if the customer phone is obviously fake. In production mode, this should be the actual user's phone number.

### 🟡 ISSUE #6: NO DEEP LINK / INTENT FILTER FOR CASHFREE

**Location:** [AndroidManifest.xml](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/AndroidManifest.xml)

The manifest has only the LAUNCHER intent filter and the notification snooze receiver. There is **no deep link intent filter** for Cashfree payment redirects. While CFDropCheckoutPayment may handle this internally, certain payment methods (UPI intent, bank redirects) may need a return URL that resolves to the app. Missing deep links can cause the app to not receive the payment callback.

---

## E. Exact Root Cause (Ranked by Probability)

| Rank | Cause | Probability | Explanation |
|------|-------|-------------|-------------|
| **#1** | **Cashfree merchant account not approved/activated for production** with package name `com.lockletpro` | **45%** | The error message is a Cashfree server-side response. The merchant account (identified by `CASHFREE_APP_ID`) may not have completed KYC, or may not have `com.lockletpro` registered as an approved Android package. This is a dashboard configuration issue, not a code issue. |
| **#2** | **Environment mismatch: SDK on PRODUCTION, backend on SANDBOX (or vice versa)** | **40%** | Release APK sets SDK to `PRODUCTION`, but if `CASHFREE_ENV` Supabase secret is not set to exactly `"PROD"`, the backend creates sandbox orders. The Cashfree SDK then tries to open a sandbox `payment_session_id` in production mode, which fails with the "not enabled" error because the session doesn't exist in production. |
| **#3** | **CASHFREE_APP_ID/SECRET not set or misconfigured in Supabase secrets** | **10%** | If the secrets were never set via `supabase secrets set`, the fallback is empty string (`""` / `''`), causing the Cashfree API to reject with a generic error. The error is then caught and returned as a generic message. |
| **#4** | **Signing certificate mismatch** | **5%** | If the APK's signing certificate SHA doesn't match what's registered in the Cashfree dashboard, Cashfree could reject the package. No `signingConfigs` in Gradle makes this a moderate risk. |

> [!IMPORTANT]
> **Most likely scenario:** The user has a release APK installed (BuildConfig.DEBUG = false → PRODUCTION mode in SDK), but either:
> - (a) `CASHFREE_ENV` is not set to `"PROD"` in Supabase secrets, so the backend creates SANDBOX orders that the PRODUCTION SDK cannot open, OR
> - (b) The Cashfree merchant account hasn't been activated for production and `com.lockletpro` isn't registered as an approved package in the Cashfree merchant dashboard.
> 
> Both conditions could be true simultaneously.

---

## F. Required Fixes (Description Only — No Code)

### Fix 1: Verify & Activate Cashfree Merchant Account (HIGHEST PRIORITY)
- Log into the **Cashfree Merchant Dashboard** (merchant.cashfree.com)
- Confirm the account has completed **KYC and production activation**
- Under **Developers > Credentials**, verify the `CASHFREE_APP_ID` matches what's in Supabase secrets
- Under **Settings > Payment Methods**, ensure payment modes are enabled
- Confirm `com.lockletpro` is registered as the Android package name under the app configuration
- Verify the API keys (App ID and Secret Key) are **production credentials**, not sandbox

### Fix 2: Unify Environment Configuration (CRITICAL)
- **Remove the `BuildConfig.DEBUG` toggle** from `SubscriptionViewModel.launchCashfree()`
- Instead, have the `create-cashfree-order` Edge Function **return the environment** along with the session ID
- OR use a single build config field (e.g., `CASHFREE_ENVIRONMENT`) in both the app and backend, ensuring they always match
- Ensure `CASHFREE_ENV` in Supabase secrets is set to exactly `"PROD"` for production

### Fix 3: Set Supabase Secrets Correctly
- Run the following commands (with actual production values):
  ```
  supabase secrets set CASHFREE_APP_ID="<production_app_id>"
  supabase secrets set CASHFREE_SECRET_KEY="<production_secret_key>"
  supabase secrets set CASHFREE_ENV="PROD"
  ```
- Verify all three are set: `supabase secrets list`

### Fix 4: Add Signing Configuration to Gradle
- Add an explicit `signingConfigs` block in `app/build.gradle.kts` for the release build
- Reference the same keystore used for Google Play upload
- Ensure the SHA-1 / SHA-256 fingerprint from this keystore is registered in the Cashfree dashboard

### Fix 5: Standardize x-api-version
- Use the same API version (`2023-08-01` or newer) across both `create-cashfree-order` and `verify-payment` Edge Functions

### Fix 6: Replace Hardcoded Customer Phone
- Pass the actual customer phone number from the app (or at minimum a validated placeholder) instead of `"9999999999"`

### Fix 7: Add Missing Deep Link Intent Filter
- Add an intent filter in the AndroidManifest for Cashfree payment return URLs if required by specific payment methods (UPI, bank redirects)

### Fix 8: Improve Logging and Error Propagation
- Log the **raw Cashfree API response** in the Edge Function before parsing
- Log the **full error response body** from Cashfree (not just `err.message`) so the exact Cashfree error code is visible
- In the Android app, log the **raw response** from the Edge Function call before parsing the JSON
- Surface meaningful error messages to the user instead of generic "Payment failed" text

---

## G. Logging Audit — Missing Instrumentation

| Location | What's Missing |
|----------|----------------|
| [create-cashfree-order/index.ts:L60](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L60) | No `console.log` of raw Cashfree response before parsing. If order creation fails, only `err.message` is returned — the Cashfree error code and details are lost. |
| [create-cashfree-order/index.ts:L36-L39](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L36-L39) | No log of which environment URL is being used. Critical for diagnosing SANDBOX vs PROD. |
| [create-cashfree-order/index.ts:L3-L5](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts#L3-L5) | No validation or log that APP_ID and SECRET are non-empty. If secrets aren't set, it silently uses `""`. |
| [SubscriptionViewModel.kt:L76-L78](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L76-L78) | Logs `raw` response but doesn't log the HTTP status code. A 500 error from Supabase could contain a Cashfree rejection message that isn't parsed properly. |
| [SubscriptionViewModel.kt:L116-L120](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/SubscriptionViewModel.kt#L116-L120) | Logs environment but doesn't log whether this is the SAME environment the order was created with. No way to detect mismatch from logs alone. |
| [MainActivity.kt:L145-L147](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/MainActivity.kt#L145-L147) | `onPaymentFailure` only logs `error?.message`. The `CFErrorResponse` object may contain additional fields (error code, status) that are discarded. |
| [verify-payment/index.ts:L42-L46](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L42-L46) | No log of raw Cashfree response for the order status check. |

---

## H. Confidence Score

| Category | Score |
|----------|-------|
| **Root cause identified** | **85%** |
| **Environment mismatch is a contributing factor** | **90%** |
| **Merchant account activation is required** | **80%** |
| **Code is structurally correct (ignoring config)** | **95%** |
| **Overall diagnosis accuracy** | **85%** |

> [!NOTE]
> The remaining 15% uncertainty stems from not being able to directly inspect:
> 1. The actual values of `CASHFREE_APP_ID`, `CASHFREE_SECRET_KEY`, and `CASHFREE_ENV` in the deployed Supabase secrets
> 2. The Cashfree merchant dashboard configuration (account status, approved packages, enabled payment methods)
> 3. The Supabase Edge Function deployment status (whether functions are actually deployed and reachable)
> 4. The APK signing key hash vs. what's registered in Cashfree
> 
> **To reach 100% certainty:** Run `supabase secrets list`, check the Cashfree merchant dashboard, and inspect Supabase function logs for the exact HTTP response from Cashfree when the order is created.

---

## I. Summary of Findings

The `"com.lockletpro is not enabled or approved"` error is **not a code bug** in the traditional sense. The subscription flow code is architecturally sound and follows the correct Cashfree SDK integration pattern. The error originates from one (or both) of two **configuration-level issues**:

1. **Environment split:** The Android SDK picks `PRODUCTION` vs `SANDBOX` based on `BuildConfig.DEBUG`, while the Supabase backend picks the Cashfree API endpoint based on a separately-configured `CASHFREE_ENV` secret. There is no mechanism to ensure these match. A release APK + misconfigured backend secret = cross-environment failure.

2. **Merchant account activation:** The error message specifically references the package name `com.lockletpro`, indicating Cashfree's servers are rejecting the integration at the account/package level. The merchant account likely needs production activation, KYC completion, and/or explicit package name registration.

**The fix is primarily operational (dashboard + secrets configuration), not code changes.** However, the environment coupling issue should also be addressed in code to prevent future recurrences.

---

**END OF REPORT — DIAGNOSIS ONLY, NO FIXES IMPLEMENTED**
