# Inline Styles Report - Frontend TSX Files

This report lists all TSX files in the Frontend directory that contain inline styles (`style={{}}`) and need to be refactored to separate CSS files.

## Files Requiring Refactoring

### High Priority (Many inline styles)

1. **EmailAccounts.tsx** - 219 inline styles
   - Location: `src/features/dashboard/components/EmailAccounts/EmailAccounts.tsx`
   - Has CSS file: Yes (`EmailAccounts.css`)
   - Status: Needs major refactoring

2. **CampaignDetail.tsx** - 147 inline styles
   - Location: `src/features/dashboard/components/Campaign/CampaignDetail.tsx`
   - Status: Needs major refactoring

3. **LeadGeneration.tsx** - 121 inline styles
   - Location: `src/features/dashboard/components/LeadGeneration/LeadGeneration.tsx`
   - Has CSS file: Yes (`LeadGeneration.css`)
   - Status: Needs major refactoring

### Medium Priority (Moderate inline styles)

4. **SelectEmailAccount.tsx** - ~8 inline styles (mostly dynamic)
   - Location: `src/features/dashboard/components/Campaign/SelectEmailAccount.tsx`
   - Has CSS file: Yes (`SelectEmailAccount.css`)
   - Status: ✅ **COMPLETED** - Most styles extracted, only dynamic styles remain

5. **Campaign.tsx** - Unknown count
   - Location: `src/features/dashboard/components/Campaign/Campaign.tsx`
   - Status: Needs checking

6. **CreateCampaign.tsx** - Unknown count
   - Location: `src/features/dashboard/components/Campaign/CreateCampaign.tsx`
   - Status: Needs checking

7. **CampaignEmailScreen.tsx** - Unknown count
   - Location: `src/features/dashboard/components/Campaign/CampaignEmailScreen.tsx`
   - Status: Needs checking

8. **PreviewCampaignDetail.tsx** - Unknown count
   - Location: `src/features/dashboard/components/Campaign/PreviewCampaignDetail.tsx`
   - Status: Needs checking

9. **DetailCampaignScreen.tsx** - Unknown count
   - Location: `src/features/dashboard/components/Campaign/DetailCampaignScreen.tsx`
   - Status: Needs checking

10. **GoogleConsentPage.tsx** - Unknown count
    - Location: `src/features/dashboard/components/EmailAccounts/GoogleConsentPage.tsx`
    - Status: Needs checking

11. **IMAPConsentPage.tsx** - Unknown count
    - Location: `src/features/dashboard/components/EmailAccounts/IMAPConsentPage.tsx`
    - Status: Needs checking

12. **Inbox.tsx** - Unknown count
    - Location: `src/features/dashboard/components/Inbox/Inbox.tsx`
    - Status: Needs checking

13. **Template.tsx** - Unknown count
    - Location: `src/features/dashboard/components/template/Template.tsx`
    - Status: Needs checking

14. **UserProfile.tsx** - Unknown count
    - Location: `src/features/dashboard/components/UserProfile/UserProfile.tsx`
    - Status: Needs checking

15. **LeadDatabase.tsx** - Unknown count
    - Location: `src/features/dashboard/components/LeadDatabase/LeadDatabase.tsx`
    - Status: Needs checking

16. **LeadLog.tsx** - Unknown count
    - Location: `src/features/dashboard/components/LeadLog/LeadLog.tsx`
    - Status: Needs checking

17. **ProfileSettings.tsx** - Unknown count
    - Location: `src/features/dashboard/components/ProfileSettings/ProfileSettings.tsx`
    - Status: Needs checking

18. **Sidebar.tsx** (dashboard) - Unknown count
    - Location: `src/features/dashboard/components/Sidebar/Sidebar.tsx`
    - Status: Needs checking

19. **Sidebar.tsx** (shared) - Unknown count
    - Location: `src/shared/components/Sidebar/Sidebar.tsx`
    - Status: Needs checking

20. **ChatPage.tsx** - Unknown count
    - Location: `src/features/chat/ChatPage.tsx`
    - Status: Needs checking

21. **BlogPost.tsx** - Unknown count
    - Location: `src/features/blog/BlogPost.tsx`
    - Status: Needs checking

22. **BlogPage.tsx** - Unknown count
    - Location: `src/features/blog/BlogPage.tsx`
    - Status: Needs checking

### Low Priority (Few inline styles)

23. **Dashboard.tsx** - 6 inline styles
    - Location: `src/features/dashboard/Dashboard.tsx`
    - Status: Minor refactoring needed

24. **HomePage.tsx** - 5 inline styles
    - Location: `src/features/homepage/HomePage.tsx`
    - Status: Minor refactoring needed

25. **AuthPage.tsx** - Unknown count
    - Location: `src/features/auth/AuthPage.tsx`
    - Status: Needs checking

26. **ForgotPassword.tsx** - Unknown count
    - Location: `src/features/auth/ForgotPassword.tsx`
    - Status: Needs checking

27. **VerifyResetOTP.tsx** - Unknown count
    - Location: `src/features/auth/VerifyResetOTP.tsx`
    - Status: Needs checking

28. **ResetPassword.tsx** - Unknown count
    - Location: `src/features/auth/ResetPassword.tsx`
    - Status: Needs checking

29. **GoogleCallback.tsx** - Unknown count
    - Location: `src/features/auth/GoogleCallback.tsx`
    - Status: Needs checking

30. **App.tsx** - Unknown count
    - Location: `src/App.tsx`
    - Status: Needs checking

31. **MobileRestrictor.tsx** - Unknown count
    - Location: `src/shared/components/MobileRestrictor/MobileRestrictor.tsx`
    - Status: Needs checking

32. **DashboardMobileRestrictor.tsx** - Unknown count
    - Location: `src/shared/components/DashboardMobileRestrictor/DashboardMobileRestrictor.tsx`
    - Status: Needs checking

33. **PopupMessage.tsx** - Unknown count
    - Location: `src/shared/components/PopupMessage/PopupMessage.tsx`
    - Status: Needs checking

34. **PublicRoute.tsx** - Unknown count
    - Location: `src/shared/components/PublicRoute/PublicRoute.tsx`
    - Status: Needs checking

35. **ProtectedRoute.tsx** - Unknown count
    - Location: `src/shared/components/ProtectedRoute/ProtectedRoute.tsx`
    - Status: Needs checking

## Recommended Action Plan

### Phase 1: High Priority Files
1. EmailAccounts.tsx (219 styles)
2. CampaignDetail.tsx (147 styles)
3. LeadGeneration.tsx (121 styles)

### Phase 2: Medium Priority Files
4. Campaign-related components
5. EmailAccounts-related components
6. Dashboard components

### Phase 3: Low Priority Files
7. Auth components
8. Shared components
9. Utility components

## Notes

- Files marked as "Has CSS file: Yes" already have a CSS file but still contain many inline styles
- Dynamic styles (e.g., `transform: rotate(${angle}deg)`) may need to remain inline
- Some inline styles might be intentional overrides that should be kept

## Total Files Found: 35 TSX files with inline styles

