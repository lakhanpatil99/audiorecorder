# LOCKLET PRO – SUBSCRIPTION ACCESS FLOW FORENSIC AUDIT

================================================
### PHASE 1 — IDENTIFY ALL SUBSCRIPTION SCREENS
================================================

| Screen | Route | Intended For | Actual Usage |
| :--- | :--- | :--- | :--- |
| `SubscriptionScreen.kt` | `subscription` | All Users | Core container. Free users should see `FreeTierView`, Premium users see `PremiumDashboardView`. |
| `FreeTierView` (Composable) | - | Free Users | Displays "Unlock Full Potential" & purchase plans. |
| `PremiumDashboardView` (Composable) | - | Premium Users | Displays "Pro is Active" and expiry date. |
| `SubscriptionHistoryScreen.kt` | `subscription_history` | Premium Users | Displays billing history. |
| `PremiumSuccessScreen.kt` | - | All Users | Shown immediately after a successful Cashfree payment. |
| `PaymentVerificationScreen.kt` | - | All Users | Shown while verifying Cashfree payment. |
| `PaymentPendingScreen.kt` | - | All Users | Shown for delayed payments. |
| `PaymentFailedScreen.kt` | - | All Users | Shown on Cashfree payment failure. |
| `PaymentCancelledScreen.kt` | - | All Users | Shown if user cancels Cashfree payment. |
| `ProfileScreen.kt` | `profile` | All Users | Contains `FreeUserUpgradeCard` and `PremiumHubCard`. |

================================================
### PHASE 2 — TRACE PROFILE FLOW
================================================

**Path for a Free User:**
1. `ProfileScreen` 
2. User sees `FreeUserUpgradeCard` ("Upgrade to Locklet Pro").
3. User taps card → Triggers `onNavigateToSubscription()`.
4. `NavGraph` catches `onNavigateToSubscription` and calls `navController.navigate(Screen.Subscription.route)`.
5. Navigates to `SubscriptionScreen`.
6. Inside `SubscriptionScreen`, it checks `isPremium`. Due to the bug, it evaluates to `true` and shows the `PremiumDashboardView` instead of `FreeTierView`.

================================================
### PHASE 3 — TRACE NAVGRAPH
================================================

**Routes Found in `NavGraph.kt`:**
- `Screen.Subscription.route` -> Renders `SubscriptionScreen`
- `Screen.SubscriptionHistory.route` -> Renders `SubscriptionHistoryScreen`

**Findings:**
- No duplicate subscription routes exist.
- No legacy or unused routes exist.
- Navigation logic correctly passes arguments and view models.

================================================
### PHASE 4 — TRACE SCREEN DECISION LOGIC
================================================

**File:** `SubscriptionScreen.kt`

**Condition Logic:**
```kotlin
val isPremium by homeViewModel.premiumStateFlow.collectAsState(initial = false)

if (isPremium) {
    PremiumDashboardView(
        planName = profileViewModel.userProfile?.planType ?: "Pro",
        expiryDate = profileViewModel.userProfile?.premiumExpiry,
        onNavigateBack = onNavigateBack,
        onBillingHistoryClick = onNavigateToBillingHistory
    )
    return
}
```

**Variable Controlling Decision:** `isPremium` (Derived from `homeViewModel.premiumStateFlow`).

================================================
### PHASE 5 — TRACE PREMIUM STATE SOURCE
================================================

**Chain of State:**
1. `SubscriptionScreen` collects `isPremium` from `homeViewModel.premiumStateFlow`.
2. `HomeViewModel` defines `premiumStateFlow = com.lockletpro.manager.SubscriptionManager.premiumState`.
3. `SubscriptionManager` defines `val premiumState: StateFlow<Boolean> = _premiumState.asStateFlow()`.
4. `SubscriptionManager` is a global `object` (Singleton) initialized in `LockletProApp.onCreate()`.

**Verification:**
The ultimate source of truth determining if the `PremiumDashboardView` is shown is the `_premiumState` variable residing inside the `SubscriptionManager` singleton.

================================================
### PHASE 6 — COMPARE TWO REAL USERS
================================================

**User A (Premium User):**
1. Logs in.
2. `SubscriptionManager` fetches profile from Supabase or completes a purchase, setting `_premiumState.value = true`.
3. User A logs out. `FirebaseAuth.getInstance().signOut()` is called, but the app process is NOT killed. `SubscriptionManager._premiumState.value` REMAINS `true`.

**User B (Free User):**
1. Logs in on the same device.
2. `ProfileViewModel` fetches User B from Supabase. Supabase correctly returns `isPremium = false`. `ProfileScreen` correctly shows the "Upgrade to Locklet Pro" card.
3. User B taps "Upgrade".
4. User B is routed to `SubscriptionScreen`.
5. `SubscriptionScreen` checks `SubscriptionManager.premiumState`. Because `SubscriptionManager` is a singleton and was never reset on logout, it still holds User A's `true` value.
6. User B is incorrectly shown the Premium Dashboard.

================================================
### PHASE 7 — TRACE BILLING HISTORY
================================================

**Investigation:**
- `SubscriptionHistoryScreen` fetches data using `supabase.from("subscriptions").select { filter { eq("firebase_uid", uid) } }`.
- This queries the database using the *currently logged-in user's UID*.

**Conclusion:**
Billing history correctly shows empty for Free users because it queries the database dynamically using the current UID. The Premium Dashboard incorrectly shows the user as premium because it relies on a local Singleton memory state (`SubscriptionManager`) that leaked across the logout boundary.

================================================
### PHASE 8 — TRACE PREMIUM DASHBOARD ENTRY CONDITIONS
================================================

**Expected Condition:**
`SubscriptionScreen` should display `PremiumDashboardView` ONLY IF the currently logged-in user's `isPremium` flag in the Supabase database is `true`.

**Actual Condition:**
`SubscriptionScreen` displays `PremiumDashboardView` if `SubscriptionManager.premiumState` is `true`. Since this singleton state leaks across sessions, it can be `true` even if the current user's database record is `false`.

================================================
### PHASE 9 — DUPLICATE SCREEN DETECTION
================================================

**Search Results:**
- **ACTIVE SCREENS:** `SubscriptionScreen`, `SubscriptionHistoryScreen`, `PremiumSuccessScreen`, `PaymentVerificationScreen`, `PaymentPendingScreen`, `PaymentFailedScreen`, `PaymentCancelledScreen`.
- **UNUSED SCREENS:** None.
- **DUPLICATE SCREENS:** None.
- **LEGACY SCREENS:** None.

There are no duplicate files or competing screens causing this issue.

================================================
### PHASE 10 — UI FLOW AUDIT
================================================

**Expected Flow (FREE USER):**
Profile -> Upgrade To Locklet Pro -> Unlock Full Potential -> Monthly / Yearly Plans -> Cashfree Purchase

**Actual Flow (FREE USER):**
Profile -> Upgrade To Locklet Pro -> **Premium Dashboard (MISMATCH)**

**Highlight of Mismatch:**
The `ProfileScreen` correctly identifies the user as Free (displaying "Upgrade to Locklet Pro") because it fetches fresh state from `ProfileViewModel` / Supabase. The `SubscriptionScreen` incorrectly identifies the user as Premium because it reads from the stale global `SubscriptionManager.premiumState`.

================================================
### PHASE 11 — ROOT CAUSE PROBABILITY
================================================

**Root Cause #1: Singleton State Leak in SubscriptionManager**
- **Confidence:** 99%
- **Reason:** `SubscriptionManager` is an `object`. Its `_premiumState` is mutated to `true` when a user subscribes. When `ProfileViewModel.logout()` is called, it clears `DocumentCache` and signs out of Firebase, but it *never* resets `SubscriptionManager._premiumState`. The stale `true` state persists in memory for the next logged-in user.

**Root Cause #2: ProfileViewModel State Override Mismatch**
- **Confidence:** 1%
- **Reason:** `ProfileViewModel` accurately fetches from Supabase and overwrites its local `isPremium` to `false`, which is why the Profile screen is correct.

**Root Cause #3: Database Data Corruption**
- **Confidence:** 0%
- **Reason:** If the database was corrupted, the `ProfileScreen` would also show the Premium Hub. The discrepancy between screens proves the database is correct but the local memory state is flawed.

================================================
### PHASE 12 — FINAL FORENSIC REPORT
================================================

1. **What is working correctly:** The `ProfileScreen` correctly identifies Free vs Premium users. `BillingHistoryScreen` correctly pulls the right history for the current user. The database contains accurate data.
2. **What is broken:** `SubscriptionScreen` relies on a global singleton state that does not clear upon user logout, causing session data leakage.
3. **Exact file responsible:** `SubscriptionManager.kt` (Missing reset logic) and `ProfileViewModel.kt` (Failing to call reset on logout).
4. **Exact composable responsible:** `SubscriptionScreen` (Reading from the leaked flow).
5. **Exact navigation route responsible:** `Screen.Subscription.route`.
6. **Exact state variable responsible:** `_premiumState` inside `SubscriptionManager`.
7. **Whether duplicate screens exist:** No.
8. **Whether duplicate routes exist:** No.
9. **Whether free users are incorrectly classified as premium:** Yes, but ONLY in local memory, not in the database.
10. **SINGLE MOST LIKELY ROOT CAUSE:** `SubscriptionManager` is a Singleton that holds `_premiumState = true` in RAM. When a user logs out, the app does not kill the process and does not call `SubscriptionManager.resetState()` to clear `_premiumState`. When a Free user logs in on the same device, `SubscriptionScreen` reads the leftover `true` value and routes them to the Premium Dashboard.
