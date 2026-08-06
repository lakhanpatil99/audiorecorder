# Locklet Pro – PIN Authentication Forensic Audit

## Phase 1 – Security Architecture Mapping

| Component | File Path | Purpose | Interaction with Auth |
| :--- | :--- | :--- | :--- |
| **Biometric Auth** | `utils/BiometricAuthManager.kt` | Manages Android `BiometricPrompt` and SharedPreferences. | Triggers the system fingerprint dialog. |
| **App Lock** | `ui/screens/settings/SecuritySettingsScreen.kt` | Security options UI. | Contains a UI toggle for App Lock, but state is not persisted. |
| **Security Screen** | `ui/screens/settings/SecuritySettingsScreen.kt` | Displays biometric/PIN toggles. | Renders options to user. |
| **Auth Screen** | `ui/screens/auth/BiometricAuthScreen.kt` | Full-screen blocking UI. | Initiates biometric prompt on load. |
| **Vault Lock** | `ui/components/BiometricLockUI.kt` | Individual document lock UI. | Prompts for biometrics to view a locked document. |
| **Splash Screen** | `ui/screens/splash/SplashScreen.kt` | Initial routing logic. | Checks Firebase session and Biometric status. |
| **Startup Flow** | `MainActivity.kt` | Host activity. | Loads `LockletNavGraph` starting at `Splash`. |
| **Nav Graph** | `ui/navigation/NavGraph.kt` | Compose Navigation routes. | Routes to `BiometricAuthScreen` or `Home`. |
| **Session Mgmt** | `viewmodel/AuthViewModel.kt` | Firebase User state. | Validates if user is logged in before security checks. |

## Phase 2 – PIN Feature Discovery

**A) Existing PIN screens:** None.
**B) Existing PIN ViewModels:** None.
**C) Existing PIN repositories:** None.
**D) Existing PIN storage logic:** None.
**E) Existing PIN preferences:** None.
**F) Existing unused PIN code:** Lucky AI (`ResponseGenerator.kt`) has canned conversational responses about setting up PINs, but the feature doesn't exist.
**G) Existing UI placeholders:**
- `SecuritySettingsScreen.kt`: Contains a "Change PIN" button with an empty `onClick = { /* Navigate to change PIN flow */ }`
- `BiometricLockUI.kt`: Contains a `Text("Use PIN Instead")` button that currently has no backing logic.

> [!WARNING]
> **Verdict:** PIN logic is **fully absent**. It is currently only UI placeholders and AI chatbot responses.

## Phase 3 – Biometric Flow Trace

**User launches app**
↓
`SplashScreen.kt` (Opens first)
↓
`SplashScreen` reads `BiometricAuthManager.isBiometricEnabled()`. If true, navigates to `Screen.Biometric.route`
↓
`BiometricAuthScreen.kt` (Composable)
↓
A `LaunchedEffect` immediately calls `biometricManager.authenticate()`
↓
Success callback executes `navController.navigate(Screen.Home.route)`

## Phase 4 – App Startup Flow

**App Launch** (`MainActivity.kt`)
↓
**Splash** (`SplashScreen.kt`)
*Security validation occurs here. Code checks Firebase Auth status, then Biometric status.*
↓
**Authentication** (`BiometricAuthScreen.kt`)
*This is the safest integration point. `SplashScreen.kt` should be modified to check both PIN and Biometric states, and route appropriately.*
↓
**Home** (`HomeScreen.kt`)

## Phase 5 – Security Settings Analysis

Inspecting `SecuritySettingsScreen.kt`:
1. **Biometric Authentication:** Real implementation. Toggle state saves to SharedPreferences via `BiometricAuthManager`.
2. **App Lock:** **Fake / Partial.** Uses a local `mutableStateOf(true)`. The value resets to `true` every time the app opens.
3. **Change PIN:** **UI only placeholder.**

**Does "Change PIN" actually do anything?** No.
- Navigation destination: None.
- Function executed: Empty lambda comment `/* Navigate to change PIN flow */`
- Stored values: None.

## Phase 6 – Storage Analysis

**Current Storage:**
- Biometric setting uses plain `SharedPreferences` in `BiometricAuthManager.kt` (File: `"locklet_prefs"`).
- **Bug Alert:** `ProfileViewModel.kt` uses a *different* `SharedPreferences` file (`"user_prefs"`) and maintains a duplicate, unused `biometric_enabled` state.
- App lock enabled key: Does not exist.
- Auto lock timer key: Does not exist.

> [!IMPORTANT]
> **Recommended Storage for PIN:** Do not use plain `SharedPreferences`. For `pin_enabled`, `pin_hash`, and `pin_created`, use **`EncryptedSharedPreferences`** (androidx.security:security-crypto) to prevent local file extraction attacks on rooted devices.

## Phase 7 – Navigation Audit

Inspected `NavGraph.kt` and `Screen.kt`.
**Does any PIN route already exist?** No.
Searches for `CreatePinScreen`, `VerifyPinScreen`, `PinEntryScreen`, and `PinLockScreen` yielded **0 results**.

## Phase 8 – Proposed User Flow Validation

The proposed user flows (First Time, Existing, App Open Cases A-D) **fit perfectly** into the current architecture.

- **Case A (Fingerprint + PIN):** Can be achieved by configuring Android's `BiometricPrompt.PromptInfo` with `DEVICE_CREDENTIAL` (which falls back to Android's system PIN), OR by adding a custom "Use PIN Instead" negative button that navigates to our custom `PinAuthScreen`.
- **Case B (PIN only):** `SplashScreen.kt` will navigate directly to `PinAuthScreen`.
- **Case C/D:** Matches current implementation.

## Phase 9 – Risk Analysis

Could PIN implementation affect:
- **Firebase Auth / Supabase / Subscription:** No risk.
- **Vault Access:** **Medium Risk.** Individual documents use `isBiometricLocked`. The `BiometricLockUI.kt` and `DocumentDetailViewModel.kt` will need to be updated to support PIN unlock for documents, otherwise users without biometrics will be locked out of vaulted documents.
- **Existing Biometric Auth:** **Low Risk.** Just requires updating the routing in `SplashScreen.kt`.

**Overall Risk Score:** 3 / 10

## Phase 10 – Implementation Readiness Score

**Files to Modify:**
- `ui/navigation/NavGraph.kt` & `Screen.kt` (Add PIN routes)
- `ui/screens/settings/SecuritySettingsScreen.kt` (Wire up UI buttons, fix fake App Lock state)
- `ui/screens/splash/SplashScreen.kt` (Add PIN check to routing logic)
- `ui/components/BiometricLockUI.kt` & `DocumentDetailViewModel.kt` (Add PIN support for documents)

**Files to Create:**
- `utils/PinManager.kt` (EncryptedSharedPreferences logic)
- `ui/screens/auth/PinAuthScreen.kt`
- `ui/screens/settings/CreatePinScreen.kt`

**Metrics:**
- Implementation Difficulty: **Medium**
- Production Risk: **Low**
- Success Probability: **95%**

### Final Verdict
1. **No functional PIN system exists.**
2. PIN is currently **100% UI placeholders**.
3. **Best insertion point:** `SplashScreen.kt` (App open) and `BiometricLockUI.kt` (Vault documents).
4. **Safest storage:** `EncryptedSharedPreferences`. Plain SharedPreferences is currently being used for biometrics, which should not be replicated for PIN hashes.
5. **Exact Architecture Recommended:** A dedicated `PinManager` handling encryption. New Compose screens for Entry and Setup. Unified auth check in `SplashScreen`.
6. **Hidden Blockers:** 
   - `ProfileViewModel` and `BiometricAuthManager` have conflicting SharedPreferences implementations for biometrics.
   - `SecuritySettingsScreen` has fake local state for App Lock and Auto-Lock Timer that resets on app restart. These must be wired up to actual storage.
