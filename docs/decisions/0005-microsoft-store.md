# 0005: Microsoft Store route

Date: 2026-10-09. Status: Accepted 2026-10-12: no Microsoft Store (D1). D2 to D4 apply only if the Store is reconsidered after 1.0.

## The question

Should mihenk be published through the Microsoft Store before 1.0, and if so by which route?

This is desk research only. Nothing was submitted and no account was created. Every claim comes
from Microsoft's own pages, tagged [1] to [21] and listed with their URLs at the end. Where a
Microsoft page does not say, the point is marked **unconfirmed**. The pages were read on
2026-10-09. The Store Policies page is version 7.20, dated 2026-09-14 [1].

## Recommendation

**No-go before 1.0.** Ship 1.0 as the direct download (the signed Inno Setup installer on GitHub)
and revisit the Store after 1.0 as an MSIX build.

Main reason: the Store is a second release pipeline, not a shortcut, and the app would have to
change to pass it. Every release is a new submission that takes up to three business days [7].
The Windows build would have to drop the Chromium download, deal with WebView2 without an online
bootstrapper, and keep user data where an uninstall does not wipe it. A privacy policy page must
be hosted. None of this is needed to reach users at 1.0, and the Store is Windows only, so macOS
still needs its own route.

What the Store would give: a free account [19], free code signing and hosting for MSIX [9], and
no SmartScreen warning on the Store install [10]. That is worth having, so it stays on the list
for after 1.0.

### Decisions for Aydin

One batch, recommendation marked on each.

| # | Decision | Recommended |
|---|---|---|
| D1 | Publish through the Store before 1.0? | **No.** Revisit after 1.0 |
| D2 | If yes later, which route? | **MSIX**, with a hand-written manifest and `makeappx`. Not the EXE/MSI route |
| D3 | Offer the Chromium download in a Store build? | **No.** Require Chrome or Edge and say so at the start of the listing description |
| D4 | Account type and publisher name, when the time comes | **Individual**, publisher display name is Aydin's own name, not "mihenk" |

Aydin's decision, 2026-10-12: no Microsoft Store. mihenk ships as the direct download.

## 1. Can a PyInstaller onedir app go to the Store?

Yes, by either route. The Store accepts MSIX packages and, since June 2021, plain EXE or MSI
installers [8] [9]. Microsoft names MSIX as the recommended format [6] [9].

### The three routes

| Route | What it is | Signing | Hosting | Silent install | Fit for mihenk |
|---|---|---|---|---|---|
| MSIX, hand-written manifest and `makeappx` | Write `AppxManifest.xml`, then `makeappx pack /d <folder> /p mihenk.msix` on the PyInstaller folder [13] [14] | None needed. The Store re-signs [6] | Microsoft hosts [9] | Not applicable, the Store installs it | **Best.** The folder already exists, no installer is run |
| MSIX Packaging Tool | Runs an existing installer on a clean machine and records what it changes. Needs Windows 10 1809 or later, administrator rights and a driver [15] [16] | "Do not sign package" is an option, so the Store can sign [16] | Microsoft hosts [9] | Not applicable | Works, but clumsy. Made for IT packaging, and it would record the WebView2 install too |
| Unpackaged EXE or MSI (the Inno installer as is) | Submit an HTTPS link to the installer [2] | You sign it, with a certificate from a CA in the Microsoft Trusted Root Program [2] [10] | You host it [9] | Required [4] | Second choice, see the table below |

### Side by side (Microsoft's own comparison [9])

| Feature | MSIX | Unpackaged EXE or MSI |
|---|---|---|
| Hosting | Free, by Microsoft | You host and pay |
| Code signing | Free, by Microsoft | You sign with a CA certificate and pay |
| Updates | The OS checks every 24 hours | The app updates itself |
| S mode | Supported | Not supported |

### What the MSIX route needs

1. Reserve the app name in Partner Center first. The manifest must carry the Identity Name and
   Publisher shown under "View app identity details", and the values are case-sensitive [6].
2. A manifest with `Windows.Desktop` as the target, `uap10:RuntimeBehavior="packagedClassicApp"`,
   `uap10:TrustLevel="mediumIL"` and the `runFullTrust` capability [13].
3. `makeappx.exe` from the Windows SDK [14]. It does not make an `.msixupload` file, but a plain
   `.msix` is on the accepted list [6] [14]. The upload file only adds a symbol file for crash
   analytics, and it can be left out [6].
4. `runFullTrust` is a restricted capability. Partner Center asks for a written reason at
   submission, it "may add some additional time", and it is generally not asked again for
   updates [17].
5. A four-part version where the fourth part is reserved for the Store and must be 0, and the
   first part cannot be 0 [6]. A 0.x build needs a mapping.
6. Test with `Add-AppxPackage -Register AppxManifest.xml` [13] and the Windows App Certification
   Kit [6].
7. Behaviour changes to plan for:
   - The package is read-only, and writing to the install folder is not supported [11] [12].
   - New files under the user's AppData go to a private per-package place, and an uninstall
     removes them [12]. If mihenk keeps its data there, an uninstall deletes the user's data.
     A Playwright Chromium download would go the same way.
   - Microsoft says to avoid writing generated code to disk: "Your application can generate code
     that it consumes in memory, but avoid writing generated code to disk because the Windows
     app certification process can't validate that code prior to app submission." [11]
8. No installer step runs, so WebView2 cannot be installed at install time. With App Installer a
   package can name the runtime as an external dependency [18], but no Microsoft page says the
   Store does the same: **unconfirmed**. The runtime "will be included as part of the Windows 11
   operating system", and "A small number of Windows 10 devices don't have the WebView2 Runtime
   installed" [18]. The app has to check at launch and tell the user.

### What the EXE or MSI route needs

| Need | Microsoft's rule | Source |
|---|---|---|
| An HTTPS direct link, versioned | "You must submit a versioned download URL in Partner Center. The binary associated with that URL must not change after submission." | [1] 10.2.9, [2] |
| A new URL for each release | "Whenever you have an updated binary to distribute, you must provide an updated versioned download URL in Partner Center" | [2] |
| Silent install | "Initiating the install must not display an installation user interface (i.e., silent install is required), however a User Account Control (UAC) dialog is allowed." The Packages page has an "Installer parameters" field where the switches go | [1] 10.2.9, [4] |
| Offline installer | "The installer is a standalone installer and is not a downloader stub/web installer that downloads bits when run." | [1] 10.2.9, [2] |
| Signing | The binary "and all of its Portable Executable (PE) files must be digitally signed" with a CA certificate in the Microsoft Trusted Root Program. The Store does not re-sign installers | [1] 10.2.9, [2], [6] |
| Own updater | "The Store does not provide these updates automatically or manually to existing users." | [5] |
| Certification | Up to three business days, malware scan, silent install test, standard-user install, clean uninstall | [3] |

### How the planned Inno Setup installer measures up

The script is `packaging/windows/mihenk.iss`, described in `docs/decisions/0003-packaging.md`.

| Planned | Store rule | Verdict |
|---|---|---|
| Per-user install under `%LOCALAPPDATA%\Programs`, no admin rights | The test checks that it "Can be successfully installed when logged in with a standard user account." [3] | Fits. Microsoft's pages do not name per-user installs, so that exact case is **unconfirmed** |
| Start menu entry and an uninstall entry | The test checks that it "Can make an entry in the Windows Start menu and Programs list" [3] | Fits |
| Clean uninstall | "Can uninstall cleanly without leaving remnants of files, folder, and registry entries." [3] | Fits for installed files. Anything the app makes later (data, a downloaded Chromium) must be removed by the uninstaller |
| Installs WebView2 with the online bootstrapper when it is missing | Offline rule above [1] [2]. The bootstrapper "downloads and installs the Evergreen Runtime from Microsoft servers" [18] | **Conflict on the strict reading.** It only runs when no runtime exists, so a Windows 11 tester may never trigger it, but do not rely on that. Fix: bundle the standalone installer ("Include the Evergreen Standalone Installer in your app installer or updater." [18]) or leave WebView2 out and check at launch |
| WebView2 as "extra software" | The bundleware test looks for "additional third-party apps that may not be related to the core purpose of your app" [3] | WebView2 is the app's window, so it is probably fine. **Unconfirmed** |
| Silent switches `/VERYSILENT /SUPPRESSMSGBOXES` (already used in 0003) | Silent install is required [4] | Enter them in "Installer parameters". The switches come from Inno Setup's own documentation, which was not re-read here |
| Unsigned beta, sign before 1.0 (0003) | All PE files signed by a CA in the Microsoft Trusted Root Program [1] [2] | Needs a CA certificate, see below |
| Hosting on GitHub Releases | HTTPS "direct link", on "your own infrastructure or CDN" [2] [6] | A tag gives a versioned URL. Microsoft names no GitHub rule, and release links redirect to another host. **Unconfirmed** that this counts as a direct link |

Signing cost for the EXE or MSI route:

- Azure Artifact Signing: "Individual developers must be located in the United States or
  Canada." [21] A Dutch individual cannot use it. The comparison table also marks it as not
  Store eligible [10].
- An OV certificate from a CA costs 150 to 300 USD a year as Microsoft states it, and since June
  2023 the private key must sit on a hardware token or HSM [10].
- Two Microsoft pages disagree on scope. The policy and requirements pages say all PE files
  "must" be signed [1] [2]. The certification page says it is "highly recommended" [3]. On the
  strict reading, every `.exe`, `.dll` and `.pyd` in the 188-file PyInstaller folder needs a
  signature (the PE count was not measured; the file count is from 0003).
- The same certificate would also fix the SmartScreen warning on the direct download, so the
  cost is not Store-only.

## 2. Do the Store policies allow this?

The policy text was searched for scraping, crawling, automation and third-party terms. **No rule
forbids an app from driving the user's own browser.** The only mention of third-party service
terms is a bullet under 10.1.6 for standalone storefronts [1], and mihenk is not one.

| Policy [1] | Text | Effect on mihenk |
|---|---|---|
| 10.2.4 | "Your product may depend on non-integrated software (such as another product, module, or service) to deliver its primary functionality if you disclose the dependency at the beginning of the description in metadata." | Needing the user's Chrome or Edge is allowed if the listing says so at the start of the description |
| 10.2.2 | "Your product must not attempt to fundamentally change or extend its described functionality or introduce features or functionality that are in violation of Store Policies through any form of dynamic inclusion of code. Your product should not, for example, download a remote script and subsequently execute that script in a manner that is not consistent with the described functionality" | The Chromium download fetches a program and runs it after install. The example is about scripts that change the app's purpose. Chromium serves the described purpose. **Unconfirmed** which way a tester reads it |
| 10.2.3 | "Further, your product must not offer to install secondary software that is not developed by you and does not enhance the functionality of your product." | Chromium is not Aydin's, but it enhances capture. Arguable. **Unconfirmed** |
| 10.1.5 | "Your product may, with user consent and after initial download of the primary product, enable acquisition of: Other products published by you as long as the other products are also distributed through the Store ... Add-ons or extensions, excluding non-Microsoft drivers or NT services, that enhance the functionality of the product." | Chromium is not a Store product. It might count as an add-on that enhances functionality. **Unconfirmed** |
| 10.2.1 | "Products that browse the web must use either the Chromium or the Gecko open-source engine." It adds a limit of two major versions behind | mihenk's own window is WebView2, which is Chromium based. Whether an app that drives other browsers counts as one that "browses the web" is **unconfirmed**. Playwright's Chromium is recent, so it would pass either way |
| 10.2.7 | "Your product must clearly communicate and enable a user's ability to cleanly uninstall and remove your product from their device." | A downloaded Chromium left behind after uninstall is a risk. Remove it in the uninstaller |
| 10.2.8 | "You are required to use supported methods and must obtain user consent to change any user's Windows settings, preferences, settings UI, or modify the user's Windows experience in any way." | Not triggered by anything in mihenk's description |
| 10.5.1 | "Product types that inherently have access to Personal Information must always have privacy policies. These include, but are not limited to, Desktop Bridge and Win32 products." | Both routes need a hosted privacy policy URL, even though nothing leaves the machine |
| 10.14 | "Company accounts must be used for organizations, businesses, and any person acting in relation to their trade or profession. Individual accounts are usually appropriate for a single developer working on their own. A company account is required if your product requires financial information for primary functionality (see Policy 10.8.3) or if a reasonable consumer would interpret your application or publisher name to be that of a business entity." | Individual is right for a free app. Use a personal publisher name, so it does not read as a business |

Reading of the Chromium download: no policy names it. The closest rules (10.2.2, 10.2.3, 10.1.5)
can be read either way, so the outcome is **unconfirmed**. Two safe ways out: drop the offer in
the Store build (decision D3), or ask Microsoft first. Certification questions go to
`reportapp@microsoft.com` [3].

Note on S mode: the unpackaged route is "Not Supported" in S mode and MSIX is "Supported" [9].

## 3. Developer account for an individual in the Netherlands

| Item | Answer | Source |
|---|---|---|
| Account type | Individual. It is for "Independent developers whose distribution of apps through the Store is not in relation to their business, trade, or profession" | [19] |
| Cost | "With the new onboarding experience, there are no registration fees for either account type". The old fee was 19 USD: "The $19 registration fee is waived in the new flow." | [19] [20] |
| Currency | Microsoft states USD only. No EUR amount was found. Whether the old fee was one-time or yearly is not stated on the pages read: **unconfirmed** | [20] |
| Where to register | Only at `https://storedeveloper.microsoft.com`. Other entry points (Partner Center, Xbox, Visual Studio) "will show the legacy flow", so do not start from Partner Center | [19] [20] |
| Identity checks | "Begin identity verification with a government-issued ID and selfie." Captured on a phone, in good light, with original documents. MFA is part of the flow | [19] [20] |
| Sign-in | A personal Microsoft account. A work (Entra) account cannot make an Individual account | [19] |
| Your ID data | Used "solely for verification". Microsoft may keep non-PII data such as publisher name and country | [19] |
| The Netherlands | The new flow is "available in nearly 200 markets worldwide" [20]. The Netherlands is not named on any page that could be opened, and the page meant to list countries and fees returned the account page instead: **unconfirmed**, though nothing excludes it | [20] |
| Locked choices | The country "cannot be changed later" [8]. Individual to Company is "not supported" [19] | [8] [19] |
| Listing needs | Privacy policy URL, age rating questionnaire, a description, one screenshot, a store logo, and "Applicable license terms" (where the PolyForm Noncommercial text would go; whether the Store accepts it is **unconfirmed**) | [4] [1] |

## What would have to change for a go

| Change | Why | Route |
|---|---|---|
| Store build never offers the Chromium download, or Microsoft confirms it in writing | 10.2.2, 10.2.3, 10.1.5 can be read either way | Both |
| Listing description says at the start that Chrome or Edge is needed (Edge is not guaranteed on every device [18]) | 10.2.4 | Both |
| A privacy policy page at a stable URL | 10.5.1 | Both |
| Test on a clean Windows 10 and Windows 11 machine, with the Windows App Certification Kit | Certification installs and runs the app [7] | Both |
| User data kept somewhere an uninstall does not remove it, or Aydin accepts the removal | MSIX uninstall removes redirected AppData writes [12] | MSIX |
| Manifest, logos, a version mapping with a non-zero first part, and the `runFullTrust` reason | [6] [13] [17] | MSIX |
| WebView2 handled without the online bootstrapper | Offline rule [1] [2] | EXE or MSI |
| An OV certificate on a hardware token, and every PE file signed | 10.2.9 [1] [10] | EXE or MSI |
| Versioned download URLs, an in-app updater, and a new submission per release | [2] [5] | EXE or MSI |

## What could not be confirmed

| Point | Why it is open |
|---|---|
| The Netherlands on the list of markets | The country and fees page returned the account page instead [20] |
| One-time or yearly old fee, and any EUR amount | Not on the pages read |
| Whether the Chromium download after install is accepted | No policy names it, see section 2 |
| Whether policy 10.2.1 covers a non-browser that drives browsers | Wording says "browse the web" only |
| Whether a nested WebView2 bootstrapper breaks the offline rule | The test text speaks of "a downloader that downloads binaries when invoked" [3] |
| Whether a per-user Inno install is treated differently | Not named on any page |
| Whether GitHub release links count as a direct link | Not named on any page |
| Whether all PE files must be signed | The policy says "must", the certification page says "highly recommended" |
| Whether the Store honours a WebView2 external dependency in a Store MSIX | Only App Installer is documented [18] |
| How a Chrome started by a packaged app behaves with the AppData redirection | Not documented, needs a real test |
| Whether PolyForm Noncommercial is accepted as the listing's license terms | Not documented |
| Any EU rule that makes an individual publisher show trader details | Not on the pages read |
| Inno Setup silent switches | From Inno's own documentation, not Microsoft's, and not re-read |

## Sources

| Tag | Page | URL |
|---|---|---|
| [1] | Microsoft Store Policies, version 7.20 | https://learn.microsoft.com/en-us/windows/apps/publish/store-policies |
| [2] | App package requirements for MSI/EXE app | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/app-package-requirements |
| [3] | The app certification process for MSI/EXE app | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/app-certification-process |
| [4] | Create an app submission for your MSI/EXE app | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/create-app-submission |
| [5] | Publish update to your MSI/EXE app on the Store | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/publish-update-to-your-app-on-store |
| [6] | App package requirements for MSIX app | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements |
| [7] | The app certification process for MSIX app | https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-certification-process |
| [8] | Get started with Microsoft Store | https://learn.microsoft.com/en-us/windows/apps/publish/get-started |
| [9] | How to distribute your Win32 application through Microsoft Store | https://learn.microsoft.com/en-us/windows/apps/distribute-through-store/how-to-distribute-your-win32-app-through-microsoft-store |
| [10] | Code signing options for Windows app developers | https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options |
| [11] | Prepare to package a desktop application (MSIX) | https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare |
| [12] | Understanding how packaged desktop apps run on Windows | https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes |
| [13] | Generating MSIX package components (manual conversion) | https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion |
| [14] | Create an app package with the MakeAppx.exe tool | https://learn.microsoft.com/en-us/windows/msix/package/create-app-package-with-makeappx-tool |
| [15] | MSIX Packaging Tool overview | https://learn.microsoft.com/en-us/windows/msix/packaging-tool/tool-overview |
| [16] | Create an MSIX package from any desktop installer | https://learn.microsoft.com/en-us/windows/msix/packaging-tool/create-app-package |
| [17] | App capability declarations (restricted capabilities) | https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations |
| [18] | Distribute your app and the WebView2 Runtime | https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution |
| [19] | Steps to open a Microsoft Store developer account in Partner Center | https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account |
| [20] | Free developer registration for individual developers | https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer |
| [21] | Quickstart: Set up Artifact Signing | https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart |
