# LOCKLET PRO — SUBSCRIPTION SYSTEM AUDIT REPORT

**Role:** Senior Android & Backend Engineer  
**Scope:** Complete read-only audit of the subscription lifecycle  
**Date:** 2026-06-14  

---

## 1. Current Implementation Flow

### 1.1 Purchase Flow (Monthly & Yearly)

```
User taps "Upgrade to Pro" on SubscriptionScreen
│
├─ SubscriptionScreen.kt (L129-L131)
│  └─ planType = "yearly" or "monthly" based on toggle
│  └─ subscriptionViewModel.startSubscription(activity, planType)
│
├─ SubscriptionViewModel.startSubscription() (L50-L101)
│  ├─ Gets FirebaseAuth.currentUser.uid
│  ├─ Calls supabase.functions.invoke("create-cashfree-order")
│  │   └─ Body: { uid, planType }
│  └─ Receives { payment_session_id, order_id }
│
├─ create-cashfree-order/index.ts (L30-L31)
│  ├─ amount = planType === "yearly" ? 14 : 10  (INR)
│  ├─ orderId = "ORDER_{uid}_{Date.now()}"
│  └─ POST → Cashfree /pg/orders
│
├─ SubscriptionViewModel.launchCashfree() (L108-L147)
│  ├─ Environment: DEBUG → SANDBOX, else → PRODUCTION
│  └─ CFPaymentGatewayService.doPayment()
│
├─ [User completes payment in Cashfree SDK]
│
├─ MainActivity.onPaymentVerify(orderId) (L136)
│  └─ subscriptionViewModel.handlePaymentSuccess(orderId)
│
├─ SubscriptionViewModel.handlePaymentSuccess() (L153-L187)
│  ├─ Calls supabase.functions.invoke("verify-payment", { order_id })
│  ├─ If "SUCCESS" → uiState = Success
│  └─ Else → falls back to verifyPaymentWithPolling()
│
├─ verify-payment/index.ts (L50-L113)
│  ├─ GET Cashfree /pg/orders/{order_id}
│  ├─ If PAID:
│  │   ├─ Extracts firebase_uid from order_id.split('_')[1]
│  │   ├─ plan_type = (amount == 14) ? 'yearly' : 'monthly'
│  │   ├─ Calculates expiryDate:
│  │   │   ├─ yearly: expiryDate.setFullYear(now.getFullYear() + 1)
│  │   │   └─ monthly: expiryDate.setMonth(now.getMonth() + 1)
│  │   ├─ UPDATE users SET is_premium=true, premium_expiry, plan_type, subscription_status='PREMIUM'
│  │   └─ INSERT INTO subscriptions (firebase_uid, plan_type, amount, purchase_date, expiry_date, order_id, payment_status='SUCCESS')
│  └─ Returns { status: "SUCCESS" }
│
└─ cashfree-webhook/index.ts (backup path — identical logic)
   ├─ HMAC-SHA256 signature verification
   └─ Same UPDATE users + INSERT subscriptions logic
```

### 1.2 Premium Status Check (Client Side)

```
App Launch / Screen Resume
│
├─ HomeViewModel.loadDocuments() (L90-L158)
│  ├─ Phase 1: Read from DocumentCache (in-memory, 5-min TTL)
│  │   └─ isPremium = cachedUser.isPremium == true       ← JUST A BOOLEAN
│  ├─ Phase 2: Fetch from Supabase users table
│  │   └─ isPremium = supabaseUser?.isPremium == true     ← JUST A BOOLEAN
│  └─ NO EXPIRY DATE COMPARISON ANYWHERE
│
├─ ProfileViewModel.loadUserProfile() (L59-L89)
│  ├─ Reads supabaseUser.isPremium, premiumExpiry, planType
│  └─ NO EXPIRY DATE COMPARISON ANYWHERE
│
├─ SubscriptionScreen.kt (L75, L115)
│  ├─ isPremium = homeViewModel.isPremium
│  └─ if (isPremium) → show PremiumSuccessScreen
│     else → show FreeTierView
│
└─ HomeScreen.kt (L334)
   └─ if (homeViewModel.isPremium) → show PremiumBadge
```

### 1.3 Premium Expiration (DOES NOT EXIST)

```
┌─────────────────────────────────────────────────┐
│                                                 │
│  THERE IS NO EXPIRY CHECK ANYWHERE.             │
│                                                 │
│  • No Supabase cron job                         │
│  • No database trigger                          │
│  • No scheduled Edge Function                   │
│  • No client-side date comparison               │
│  • No pg_cron extension usage                   │
│                                                 │
│  ONCE is_premium = true, IT STAYS TRUE FOREVER  │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 1.4 Billing History

```
SubscriptionHistoryScreen → SubscriptionHistoryViewModel.fetchHistory()
│
├─ supabase.from("subscriptions").select { filter { eq("firebase_uid", uid) } }
├─ Decoded as List<SubscriptionHistory>
├─ Sorted by purchaseDate descending
└─ Displayed in HistoryItemCard (purchase date, expiry date, amount, status)
```

> [!NOTE]
> Billing History reads from the `subscriptions` table independently of `is_premium`. This means history survives premium expiry — **correct behavior**.

### 1.5 Login/Logout Behavior

```
Logout:
  ProfileViewModel.logout() (L112-L116)
  └─ FirebaseAuth.getInstance().signOut()
  └─ onLogout() callback → navigates to login screen
  └─ ⚠️ DocumentCache.clearAll() is NEVER called

Login:
  AuthViewModel → navigates to HomeScreen
  └─ HomeViewModel.loadDocuments() fetches fresh user + documents
  └─ Previous user's cached data may still be in memory
```

---

## 2. Potential Bugs

### 🔴 BUG #1 (CRITICAL): Premium NEVER Expires

**Files:** All ViewModels + All Edge Functions  
**Impact:** Revenue loss, users get permanent premium for a single payment

The entire system treats `is_premium` as a permanent boolean flag. After payment verification sets `is_premium = true` in the `users` table, **nothing ever sets it back to `false`**.

The `premium_expiry` field is stored but never compared against the current time — not on the server, not on the client, not by any scheduled job.

**Evidence:**
- [HomeViewModel.kt:L110,L129](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/HomeViewModel.kt#L110) — reads `isPremium` boolean, never checks `premiumExpiry`
- [ProfileViewModel.kt:L75](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/ProfileViewModel.kt#L75) — reads `isPremium` boolean, stores `premiumExpiry` for display only
- No `pg_cron` setup in project
- No Supabase scheduled function for expiry processing
- `grep -r "cron" supabase/` → **No results**

---

### 🔴 BUG #2 (CRITICAL): JavaScript `setMonth` Overflow

**Files:** [verify-payment/index.ts:L64-L68](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L64-L68), [cashfree-webhook/index.ts:L53-L57](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/cashfree-webhook/index.ts#L53-L57)

```typescript
const expiryDate = new Date()        // ← creates SECOND Date object
if (plan_type === 'yearly') {
    expiryDate.setFullYear(now.getFullYear() + 1)
} else {
    expiryDate.setMonth(now.getMonth() + 1)   // ← OVERFLOW BUG
}
```

**Problem 1: Two `new Date()` calls**  
`now` and `expiryDate` are separate `new Date()` calls. In edge cases they could differ by milliseconds, and for yearly plans `expiryDate.setFullYear(now.getFullYear() + 1)` sets the year based on `now` but the month/day come from `expiryDate` — usually fine but technically a race.

**Problem 2: `setMonth` overflow for months with 31 days**  
JavaScript's `Date.setMonth()` overflows into the next month when the current day exceeds the target month's length:

| Purchase Date | Expected Expiry | Actual Expiry |
|---------------|----------------|---------------|
| Jan 31 | Feb 28 | **Mar 3** ❌ |
| Mar 31 | Apr 30 | **May 1** ❌ |
| May 31 | Jun 30 | **Jul 1** ❌ |
| Aug 31 | Sep 30 | **Oct 1** ❌ |
| Oct 31 | Nov 30 | **Dec 1** ❌ |

This means 5 out of 12 months have incorrect monthly expiry dates.

---

### 🔴 BUG #3 (HIGH): Cache Not Cleared on Logout

**File:** [ProfileViewModel.kt:L112-L116](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/ProfileViewModel.kt#L112-L116)

```kotlin
fun logout(onLogout: () -> Unit) {
    FirebaseAuth.getInstance().signOut()
    onLogout()
    // ⚠️ DocumentCache.clearAll() is NEVER called
}
```

**Impact:** If User A (premium) logs out and User B (free) logs in on the same device, User B may briefly see User A's premium status and documents from the in-memory cache before the network fetch completes.

---

### 🟡 BUG #4 (MEDIUM): Plan Type Detected by Amount, Not by Actual Plan

**Files:** [verify-payment/index.ts:L58](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L58), [cashfree-webhook/index.ts:L48](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/cashfree-webhook/index.ts#L48)

```typescript
const plan_type = amount == 14 ? 'yearly' : 'monthly'
```

The plan type is reverse-engineered from the payment amount instead of being stored in the order metadata. If prices change, this logic silently miscategorizes plans. Additionally, it uses loose equality (`==`) which could cause type coercion issues if `amount` arrives as a string.

---

### 🟡 BUG #5 (MEDIUM): Firebase UID Extraction from Order ID is Fragile

**Files:** [verify-payment/index.ts:L54-L55](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L54-L55)

```typescript
const parts = order_id.split('_')
const firebase_uid = parts.length > 1 ? parts[1] : null
```

Order format: `ORDER_{uid}_{timestamp}`. If a Firebase UID ever contains an underscore (unlikely but possible with custom auth), this extraction would break silently, returning only the portion before the first underscore.

---

### 🟡 BUG #6 (MEDIUM): `refreshDocuments()` Doesn't Update `isPremium`

**File:** [HomeViewModel.kt:L170-L203](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/HomeViewModel.kt#L170-L203)

```kotlin
private suspend fun loadDocumentsInternal(forceRefresh: Boolean) {
    // ...
    userName = supabaseUser?.name ?: user.displayName ?: "User"
    isUserLoaded = true
    // ⚠️ isPremium is NOT updated here!
}
```

The `refreshDocuments()` path (pull-to-refresh) calls `loadDocumentsInternal()` which updates `userName` and `isUserLoaded` but **never updates `isPremium`**. This means a pull-to-refresh won't reflect premium status changes until a full `loadDocuments()` call.

---

## 3. Security Issues

### 🔴 SEC-1: No Server-Side Expiry Enforcement

Since premium status is only set to `true` and never revoked, there is **zero server-side enforcement** of subscription expiry. Even if a client-side check were added, a user could:
- Use an older APK version without the check
- Modify the APK to remove the check
- Direct-query the Supabase API

**Fix required:** Server-side cron job to revoke expired premiums.

---

### 🔴 SEC-2: Device Time Manipulation (If Client-Side Check Added)

If a future client-side expiry check uses `LocalDate.now()` or `System.currentTimeMillis()`, users can set their device clock forward/backward to bypass it. Since there's currently NO check, this is moot — but any future fix must use **server time only**.

---

### 🟡 SEC-3: No Authentication on verify-payment Edge Function

[verify-payment/index.ts](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts) accepts any `order_id` without verifying the caller's identity. An attacker who knows an order ID pattern could call this endpoint and trigger premium activation for any user.

---

### 🟡 SEC-4: Premium Status Readable from Cached Stale Data

The [DocumentCache](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/data/cache/DocumentCache.kt) has a 5-minute TTL. During that window, if the server revokes premium (via a future cron), the client still shows premium from stale cache.

---

## 4. Date Calculation Issues

### 4.1 Monthly Calculation

| Scenario | Code | Result |
|----------|------|--------|
| Normal months (e.g., Mar 1 + 1 month) | `setMonth(2 + 1)` = Apr 1 | ✅ Correct |
| 31-day months (e.g., Jan 31 + 1 month) | `setMonth(0 + 1)` = Mar 3 | ❌ **Overflows to March** |
| Dec 31 + 1 month | `setMonth(11 + 1)` = Jan 31 next year | ✅ Correct (month 12 wraps) |
| Feb 28 + 1 month (non-leap) | `setMonth(1 + 1)` = Mar 28 | ✅ Correct |

### 4.2 Yearly Calculation

| Scenario | Code | Result |
|----------|------|--------|
| Normal dates | `setFullYear(2026 + 1)` = same date 2027 | ✅ Correct |
| Feb 29 (leap year) + 1 year | `setFullYear(2028 + 1)` = Mar 1, 2029 | ⚠️ **Shifts to March 1** |

### 4.3 Price → Plan Inference

| Android Sends | Cashfree Amount | Backend Infers |
|---------------|----------------|----------------|
| `planType: "monthly"` | ₹10 | `amount == 14` → false → `"monthly"` ✅ |
| `planType: "yearly"` | ₹14 | `amount == 14` → true → `"yearly"` ✅ |
| *(future price change)* | ₹99 | `amount == 14` → false → `"monthly"` ❌ |

---

## 5. Timezone Issues

### 5.1 Backend (Supabase Edge Functions — Deno Runtime)

- `new Date()` in Deno Edge Functions uses **UTC**
- `expiryDate.toISOString()` outputs UTC (e.g., `2026-04-01T08:15:00.000Z`)
- This is **correct** for storage

### 5.2 Client (Android — Kotlin)

- Display in [SubscriptionHistoryScreen.kt:L170-L180](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/subscription/SubscriptionHistoryScreen.kt#L170-L180):
  ```kotlin
  item.purchaseDate?.substring(0, 19)?.let { LocalDateTime.parse(it) }
  ```
  This strips the timezone `Z` suffix and parses as a local datetime — meaning a purchase at `2026-03-01T23:30:00Z` (UTC) would display as "01 Mar 2026" instead of "02 Mar 2026" (which it is in IST).

- Display in [PremiumSuccessScreen.kt:L181-L185](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/subscription/PremiumSuccessScreen.kt#L181-L185) and [ProfileScreen.kt:L580-L592](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/profile/ProfileScreen.kt#L580-L592):
  Same pattern — `take(19)` strips timezone.

### 5.3 Impact

| Time of Purchase (UTC) | Stored As | Displayed (IST User) | Expected (IST) |
|------------------------|-----------|----------------------|-----------------|
| `2026-03-01T23:30:00Z` | `2026-03-01T23:30:00.000Z` | 01 Mar 2026 | **02 Mar 2026** |
| `2026-06-14T18:45:00Z` | `2026-06-14T18:45:00.000Z` | 14 Jun 2026 | 15 Jun 2026 *(if after midnight IST)* |

**Impact:** Dates can appear **off by 1 day** for IST users who purchase late at night.

---

## 6. Edge Cases

| # | Edge Case | Current Behavior | Expected Behavior |
|---|-----------|-----------------|-------------------|
| 1 | User's premium expires | **Premium remains active forever** | Premium should be revoked |
| 2 | User changes device clock back | No effect (no expiry check exists) | Should be immune (server-time only) |
| 3 | User changes device clock forward | No effect (no expiry check exists) | Should be immune (server-time only) |
| 4 | App restarted after expiry | Premium still shows (is_premium=true in DB) | Should show free tier |
| 5 | Purchase on Jan 31 (monthly) | Expires Mar 3 (wrong) | Should expire Feb 28 |
| 6 | Purchase on Feb 29 (yearly, leap year) | Expires Mar 1 next year | Should expire Feb 28 |
| 7 | User A (premium) logs out, User B logs in | User B briefly sees User A's data from cache | Cache should be cleared |
| 8 | Two concurrent payments for same user | Both may insert into subscriptions | Should be idempotent |
| 9 | Webhook + verify-payment race condition | Both try to UPDATE + INSERT; webhook has idempotency check | Mostly safe but both `expiryDate` calculations use `new Date()` independently |
| 10 | User purchases monthly, then yearly before expiry | New purchase overwrites `premium_expiry` | Should extend from current expiry, not from `now` |
| 11 | Payment succeeds but verify-payment call fails | Falls back to polling `is_premium` every 3s × 10 | ✅ Correct fallback |
| 12 | Firebase UID contains underscore | `order_id.split('_')[1]` truncates UID | Should use last segment for timestamp, rest for UID |
| 13 | Price changed to ₹99/year | `amount == 14 ? 'yearly' : 'monthly'` → classified as monthly | Plan type should be stored in order metadata |
| 14 | Network failure during loadDocuments | Falls back to cache, shows "Offline mode" | ✅ Correct |
| 15 | Billing history after expiry | History still visible from subscriptions table | ✅ Correct |
| 16 | User documents after expiry | Documents never deleted | ✅ Correct |
| 17 | User account after expiry | Account never deleted | ✅ Correct |

---

## 7. Recommended Fixes (Priority Ordered)

### FIX 1: Server-Side Premium Expiry Cron (CRITICAL)

**What:** Add a Supabase `pg_cron` job or a scheduled Edge Function that runs every hour and revokes expired premiums.

**SQL approach (pg_cron):**
```sql
-- Run every hour
SELECT cron.schedule('revoke-expired-premiums', '0 * * * *', $$
  UPDATE users
  SET is_premium = false,
      subscription_status = 'EXPIRED'
  WHERE is_premium = true
    AND premium_expiry IS NOT NULL
    AND premium_expiry < NOW();
$$);
```

**Why:** This is the ONLY reliable way to enforce expiry. Client-side checks are bypassable.

---

### FIX 2: Client-Side Expiry Guard (IMPORTANT — Defense in Depth)

**What:** Add a client-side check in `HomeViewModel` and `ProfileViewModel` that compares `premiumExpiry` against the **server-fetched** current time (or at minimum, the device time as a first approximation).

**Where:** [HomeViewModel.kt:L110,L129](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/HomeViewModel.kt#L110)

**Logic:**
```kotlin
val serverExpiry = supabaseUser?.premiumExpiry
val effectivePremium = supabaseUser?.isPremium == true && 
    (serverExpiry == null || Instant.parse(serverExpiry).isAfter(Instant.now()))
isPremium = effectivePremium
```

**Why:** Provides immediate UI feedback even before the server cron runs. Not a replacement for server-side enforcement.

---

### FIX 3: Fix JavaScript `setMonth` Overflow (HIGH)

**What:** Clamp the day to the last valid day of the target month.

**Where:** [verify-payment/index.ts:L63-L69](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/verify-payment/index.ts#L63-L69), [cashfree-webhook/index.ts:L52-L58](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/cashfree-webhook/index.ts#L52-L58)

**Fix:**
```typescript
const now = new Date()
const expiryDate = new Date(now)
if (plan_type === 'yearly') {
    expiryDate.setFullYear(expiryDate.getFullYear() + 1)
} else {
    // Safe month increment: clamp to last day of target month
    const targetMonth = expiryDate.getMonth() + 1
    expiryDate.setDate(1)  // avoid overflow
    expiryDate.setMonth(targetMonth)
    // Set to last day of target month or original day, whichever is smaller
    const lastDay = new Date(expiryDate.getFullYear(), expiryDate.getMonth() + 1, 0).getDate()
    expiryDate.setDate(Math.min(now.getDate(), lastDay))
}
```

---

### FIX 4: Clear Cache on Logout (HIGH)

**Where:** [ProfileViewModel.kt:L112-L116](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/ProfileViewModel.kt#L112-L116)

**Fix:**
```kotlin
fun logout(onLogout: () -> Unit) {
    viewModelScope.launch {
        DocumentCache.clearAll()
        FirebaseAuth.getInstance().signOut()
        onLogout()
    }
}
```

---

### FIX 5: Store Plan Type in Order Metadata (MEDIUM)

**Where:** [create-cashfree-order/index.ts](file:///d:/Antigravity%20Projects/tests/LockletPro/supabase/functions/create-cashfree-order/index.ts)

Store `planType` in the Cashfree order's `order_tags` or `order_note` field, then read it back in `verify-payment` instead of inferring from amount.

---

### FIX 6: Convert Dates to IST for Display (MEDIUM)

**Where:** [SubscriptionHistoryScreen.kt:L170-L180](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/subscription/SubscriptionHistoryScreen.kt#L170-L180), [PremiumSuccessScreen.kt:L181-L185](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/ui/screens/subscription/PremiumSuccessScreen.kt#L181-L185)

**Fix:** Parse as `Instant` or `ZonedDateTime` and convert to the device's timezone:
```kotlin
val instant = Instant.parse(item.purchaseDate)
val localDate = instant.atZone(ZoneId.systemDefault()).toLocalDate()
val formatted = localDate.format(DateTimeFormatter.ofPattern("dd MMM yyyy"))
```

---

### FIX 7: Fix `refreshDocuments` Missing `isPremium` Update (MEDIUM)

**Where:** [HomeViewModel.kt:L185-L186](file:///d:/Antigravity%20Projects/tests/LockletPro/app/src/main/java/com/lockletpro/viewmodel/HomeViewModel.kt#L185-L186)

Add `isPremium = supabaseUser?.isPremium == true` to the `loadDocumentsInternal()` method.

---

### FIX 8: Handle Subscription Stacking / Renewals (LOW)

Currently, a new purchase **overwrites** the `premium_expiry` calculated from `new Date()` (now). If a user renews 10 days before their current subscription expires, they lose those 10 days.

**Fix:** Check the current `premium_expiry` and calculate the new expiry from `max(now, current_expiry)`:
```typescript
const existingUser = await supabase.from('users').select('premium_expiry').eq('firebase_uid', firebase_uid).single()
const baseDate = existingUser?.data?.premium_expiry 
    ? new Date(Math.max(new Date(existingUser.data.premium_expiry).getTime(), now.getTime()))
    : now
```

---

## Summary Scorecard

| Audit Item | Status | Finding |
|------------|--------|---------|
| 1. Monthly purchase | ✅ Works | Correct flow, but `setMonth` bug on 31st |
| 2. Yearly purchase | ✅ Works | Correct flow, minor leap year edge case |
| 3. Premium activation | ✅ Works | Correctly sets `is_premium = true` + fields |
| 4. Premium expiration | 🔴 **BROKEN** | **Never expires — no enforcement exists** |
| 5. Billing History screen | ✅ Works | Independent of premium status |
| 6. Premium feature access | ⚠️ Partial | Checks `isPremium` boolean, but that boolean never reverts |
| 7. App restart behavior | ✅ Works | Re-fetches from Supabase; premium persists (but never revokes) |
| 8. Login/logout behavior | 🟡 Bug | Cache not cleared — cross-user data leak possible |
| 9. Device time manipulation | 🔴 **N/A** | No check exists to bypass; any future check must use server time |
| 10. Server time validation | 🔴 **MISSING** | No server-side expiry validation at all |
| 11. Supabase premium storage | ✅ Works | Correct schema and fields |
| 12. Expiry date calculation | 🟡 Bug | `setMonth` overflow on 31-day months |
| 13. Expiry date comparison | 🔴 **MISSING** | No comparison exists anywhere |
| 14. Automatic premium removal | 🔴 **MISSING** | No mechanism exists |

> [!CAUTION]
> **Bottom line:** The subscription system successfully processes payments and activates premium, but **premium access never expires**. Any user who purchases a ₹10 monthly plan gets permanent premium access. This is the highest-priority fix needed before production launch.

---

**END OF AUDIT — FIXES NOT YET IMPLEMENTED**
