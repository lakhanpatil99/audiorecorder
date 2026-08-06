# Locklet Pro - Subscription Forensic Audit Report

## Phase 1: Complete Payment Flow Trace
**Path:** `SubscriptionScreen` → `SubscriptionViewModel` → `SubscriptionManager` → `Cashfree SDK`
1. User clicks the purchase button in `SubscriptionScreen.kt` (Line 185).
2. It triggers `subscriptionViewModel.startSubscription(activity, planType)`.
3. `SubscriptionManager.startSubscription` invokes the Supabase edge function `create-cashfree-order`.
4. The manager saves the `LaunchingPayment` state locally and calls `CFPaymentGatewayService.getInstance().doPayment`.
**Status:** Working as intended.

## Phase 2: Success Callback Trace
**Path:** `MainActivity` → `SubscriptionManager` → `UserRepository`
1. Cashfree finishes and triggers `MainActivity.onPaymentVerify(orderId)`.
2. This routes to `SubscriptionManager.handlePaymentSuccess`, setting the state to `Verifying`.
3. `verifyPayment(orderId)` calls the `verify-payment` edge function.
4. On `"SUCCESS"`, it fetches the user profile via `userRepository.getCurrentUser(forceRefresh = true)` and sets `_premiumState`.
**Status:** Flawed. (See Phase 4 & 5).

## Phase 3: App Close / Disappear Issue
**Root Cause: Process Death & Inadequate State Recovery**
1. **The Disappearance:** When Cashfree opens (or the user is redirected to a UPI app), LockletPro is sent to the background. If the OS needs memory, it kills the LockletPro process.
2. **The Recreation:** Upon finishing payment, the OS recreates `MainActivity`. `LockletNavGraph` restarts from the default `Screen.Splash.route`, forcing the user to see the splash screen and re-authenticate. To the user, the app "disappeared."
3. **The State Loss:** During recreation, `SubscriptionManager.initialize()` calls `recoverState()`. However, `recoverState()` only handles `Verifying` and `PaymentPending`. Since the app died during `LaunchingPayment`, it hits `else -> clearSavedState()`, permanently losing the `orderId` and failing to verify the payment.

## Phase 4 & 5: Premium State & Billing History Mismatch
**Root Cause: Edge Function vs. Webhook Race Condition**
- **Why Billing History Succeeds:** Cashfree sends a background webhook to Supabase, which reliably updates the `subscriptions` table and `users.isPremium` status.
- **Why UI Activation Fails:** In `SubscriptionManager.kt` (Lines 248-257), when the edge function returns `"SUCCESS"`, the code immediately fetches the user profile **exactly once** and applies it to `_premiumState`. 
- **The Race:** The Android app requests the profile *milliseconds* after the edge function returns, **beating the Cashfree webhook** to the database. The database still says `isPremium = false`. The app caches `false`, sets `PaymentState.Success` (showing the success screen), but the global premium badge never activates.

## Phase 6: Buy Button Visibility Bug
**Root Cause: Flawed Premium UI Logic**
In `SubscriptionScreen.kt` (Lines 124-131):
```kotlin
    if (isPremium) {
        PremiumSuccessScreen(
            isJustPurchased = false,
            expiryDate = profileViewModel.userProfile?.premiumExpiry,
            onContinue = onNavigateBack
        )
        return
    }
```
**Bug:** If a user is premium, the app permanently shows the `PremiumSuccessScreen` (a transient graphical overlay) instead of a "Manage Subscription" dashboard. The buttons are hidden, but the user is trapped on a success screen where the only action is to pop the backstack.

## Phase 7: Navigation Trace
**Root Cause: Incorrect Navigation Action**
- **Expected:** Payment Success → Return Home.
- **Actual:** `PaymentState.Success` triggers `PremiumSuccessScreen`. The "Continue" button invokes `onNavigateBack`, which executes `navController.popBackStack()`. This drops the user back on the `ProfileScreen`, not the `HomeScreen`.

## Phase 8: Supabase Verification
Database updates correctly via Cashfree webhooks, confirming the issue is entirely on the client-side state management and synchronization timing.

---

## Phase 9: Final Root Cause Report

### What is working:
Order creation, Cashfree SDK integration, Webhook database updates, and Billing History queries.

### What is broken:
1. Immediate UI premium activation.
2. App resilience against Process Death during checkout.
3. Subscription Screen UI for already-premium users.

### Exact File & Function:
**File:** `d:/Antigravity Projects/tests/LockletPro/app/src/main/java/com/lockletpro/manager/SubscriptionManager.kt`
**Function:** `verifyPayment(orderId: String)`
**Line Area:** 248 - 257

### The SINGLE most likely root cause:
**Race condition in `verifyPayment`.** The code bypasses the polling mechanism (`verifyPaymentWithPolling`) when the edge function returns `"SUCCESS"`. It fetches the user profile instantly, missing the asynchronous webhook database update, locking the UI into a `false` premium state while the database is actually updated moments later.
