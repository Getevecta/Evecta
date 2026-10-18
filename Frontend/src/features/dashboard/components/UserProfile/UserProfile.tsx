import { useState, useEffect, useRef } from 'react';
import { Save, Camera, Sparkles, User, Lock, Eye, EyeOff, AlertCircle, X, CheckCircle2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs';
import { Badge } from '../ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { useAuth } from '../../../../shared/contexts/AuthContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { apiService } from '../../../../shared/services/api';
import { ProfileSettings } from '../ProfileSettings/ProfileSettings';
import { useMobileGap } from '../ui/use-mobile-gap';
import './UserProfile.css';

const USER_PROFILE_TAB_KEYS = ['profile', 'business', 'password', 'account'] as const;

const CANCELLATION_FEEDBACK_REASONS = [
  "It's too expensive",
  'I no longer need it',
  'Quality was less than expected',
  'I need more features',
  'I found an alternative',
  'Other reason',
] as const;

interface UserProfileProps {
  onToggleSidebar?: () => void;
}

export function UserProfile({ onToggleSidebar }: UserProfileProps) {
  // Mobile gap helpers
  const gap4 = useMobileGap(4);
  const gap6 = useMobileGap(6);
  const gap8 = useMobileGap(8);
  const gap10 = useMobileGap(10);
  const gap12 = useMobileGap(12);
  const gap16 = useMobileGap(16);
  const gap18 = useMobileGap(18);
  const gap24 = useMobileGap(24);
  
  const { user, setUser, logout } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState('profile'); // profile | business | account | password

  useEffect(() => {
    const t = searchParams.get('tab');
    if (t && (USER_PROFILE_TAB_KEYS as readonly string[]).includes(t)) {
      setActiveTab(t);
    }
  }, [searchParams]);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', value);
        return next;
      },
      { replace: true },
    );
  };
  
  // Statistics state
  const [statistics, setStatistics] = useState({
    leadsGenerated: 0,
    campaignsCreated: 0,
    sequencesCreated: 0,
    emailsSent: 0,
    loading: true
  });
  
  // Form state
  const [formData, setFormData] = useState({
    fullName: '',
    email: '',
    department: '',
    location: '',
    website: '',
    bio: ''
  });

  // Profile image state
  const [profileImage, setProfileImage] = useState<string | null>(user?.profile_image || null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Password state
  const [passwordData, setPasswordData] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });

  // Password visibility toggles
  const [showPasswords, setShowPasswords] = useState({
    current: false,
    new: false,
    confirm: false
  });

  // Password validation errors
  const [passwordErrors, setPasswordErrors] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });

  // Top-right error message
  const [topErrorMessage, setTopErrorMessage] = useState<string>('');

  // Top-right success message
  const [topSuccessMessage, setTopSuccessMessage] = useState<string>('');

  // Company profile state
  const [companyProfile, setCompanyProfile] = useState<any>(null);
  const [isCompanyProfileIncomplete, setIsCompanyProfileIncomplete] = useState(false);
  const [isLoadingCompany, setIsLoadingCompany] = useState(true);

  const [billingSubscription, setBillingSubscription] = useState<{
    plan?: string;
    stripe_customer_id?: string | null;
    stripe_subscription_id?: string | null;
    cancel_at?: string | null;
  }>({
    plan: 'free',
    stripe_customer_id: null,
    stripe_subscription_id: null,
    cancel_at: null,
  });
  const [portalLoading, setPortalLoading] = useState(false);
  const [showCancellationFeedbackModal, setShowCancellationFeedbackModal] = useState(false);
  const [cancellationReason, setCancellationReason] = useState<string>('');
  const [cancellationDetails, setCancellationDetails] = useState('');
  const [cancellationFeedbackSubmitting, setCancellationFeedbackSubmitting] = useState(false);

  // Business Information form state
  const [businessFormData, setBusinessFormData] = useState({
    company_name: '',
    company_description: '',
    company_website: '',
    business_email: '',
    state: '',
    country: '',
    products_and_services: [] as string[],
    target_industry: '',
    target_location: '',
    experience_with_lead_gen_tools: '',
    lead_generation_expect_monthly: ''
  });

  // Check if company profile is incomplete
  useEffect(() => {
    const checkCompanyProfile = async () => {
      if (!user) {
        setIsLoadingCompany(false);
        return;
      }

      try {
        const response = await apiService.getMyCompany();
        
        if (response.data) {
          setCompanyProfile(response.data);
          // Initialize business form data
          const products = response.data.products_and_services 
            ? (Array.isArray(response.data.products_and_services) 
                ? response.data.products_and_services.map((item: any) => typeof item === 'string' ? item : (item.name || item.title || JSON.stringify(item)))
                : [])
            : [];
          
          setBusinessFormData({
            company_name: response.data.company_name && response.data.company_name !== 'N/A' ? response.data.company_name : '',
            company_description: response.data.company_description || '',
            company_website: response.data.company_website || '',
            business_email: response.data.business_email || '',
            state: response.data.state || '',
            country: response.data.country || '',
            products_and_services: products,
            target_industry: response.data.target_industry && response.data.target_industry !== 'N/A' ? response.data.target_industry : '',
            target_location: response.data.target_location && response.data.target_location !== 'N/A' ? response.data.target_location : '',
            experience_with_lead_gen_tools: response.data.experience_with_lead_gen_tools && response.data.experience_with_lead_gen_tools !== 'N/A' ? response.data.experience_with_lead_gen_tools : '',
            lead_generation_expect_monthly: response.data.lead_generation_expect_monthly && response.data.lead_generation_expect_monthly !== 'N/A' ? response.data.lead_generation_expect_monthly : ''
          });

          // Check if profile is incomplete (has 'N/A' values or missing required fields)
          const isIncomplete = 
            !response.data.role || 
            response.data.role === 'N/A' ||
            !response.data.company_size || 
            response.data.company_size === 'N/A' ||
            !response.data.target_industry || 
            response.data.target_industry === 'N/A' ||
            !response.data.target_location || 
            response.data.target_location === 'N/A' ||
            !response.data.experience_with_lead_gen_tools || 
            response.data.experience_with_lead_gen_tools === 'N/A' ||
            !response.data.lead_generation_expect_monthly || 
            response.data.lead_generation_expect_monthly === 'N/A';
          
          setIsCompanyProfileIncomplete(isIncomplete);
        } else {
          // No company profile exists
          setIsCompanyProfileIncomplete(false);
        }
      } catch (error) {
        console.error('Error checking company profile:', error);
        setIsCompanyProfileIncomplete(false);
      } finally {
        setIsLoadingCompany(false);
      }
    };

    checkCompanyProfile();
  }, [user]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await apiService.getBillingSubscription();
      if (cancelled || !res.data) return;
      setBillingSubscription(res.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const openBillingPortal = async () => {
    if (!billingSubscription.stripe_customer_id) {
      toast.error('Complete billing in Plan & usage first so your account is linked to Stripe.');
      return;
    }
    sessionStorage.setItem('portal_cancel_at_before', billingSubscription.cancel_at ?? '');
    setPortalLoading(true);
    try {
      const res = await apiService.createBillingPortalSession();
      if (res.error) {
        toast.error(res.error);
        return;
      }
      const url = res.data?.url;
      if (!url?.trim()) {
        toast.error('Could not open the billing portal.');
        return;
      }
      window.location.assign(url);
    } finally {
      setPortalLoading(false);
    }
  };

  const submitCancellationFeedback = async () => {
    if (!cancellationReason.trim()) {
      toast.error('Please select a reason.');
      return;
    }
    setCancellationFeedbackSubmitting(true);
    try {
      const res = await apiService.submitCancellationFeedback(cancellationReason, cancellationDetails);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      toast.success(res.data?.message ?? 'Thanks for your feedback.');
      setShowCancellationFeedbackModal(false);
      setCancellationReason('');
      setCancellationDetails('');
    } finally {
      setCancellationFeedbackSubmitting(false);
    }
  };

  useEffect(() => {
    if (searchParams.get('portal_return') !== '1') return;
    let cancelled = false;
    (async () => {
      const subRes = await apiService.getBillingSubscription();
      if (cancelled || !subRes.data) return;
      const after = subRes.data.cancel_at ?? '';
      const before = sessionStorage.getItem('portal_cancel_at_before') ?? '';
      sessionStorage.removeItem('portal_cancel_at_before');
      setBillingSubscription(subRes.data);
      if (after && after !== before) {
        setShowCancellationFeedbackModal(true);
      }
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('portal_return');
          return next;
        },
        { replace: true },
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [searchParams, setSearchParams]);

  const showTopError = (message: string) => {
    setTopErrorMessage(message);
    toast(message);
  };

  const showTopSuccess = (message: string) => {
    setTopSuccessMessage(message);
    toast(message);
  };

  // Initialize form data from user and company profile
  useEffect(() => {
    if (user) {
      setFormData({
        fullName: user.full_name || user.username || '',
        email: user.email || '',
        department: user.department || (companyProfile?.role && companyProfile.role !== 'N/A' ? companyProfile.role : ''),
        location: user.location || (companyProfile?.target_location && companyProfile.target_location !== 'N/A' ? companyProfile.target_location : ''),
        website: user.website || companyProfile?.company_website || '',
        bio: user.bio || ''
      });
      setProfileImage(user.profile_image || null);
    }
  }, [user, companyProfile]);

  // Fetch user statistics
  useEffect(() => {
    const fetchStatistics = async () => {
      if (!user) return;
      
      setStatistics(prev => ({ ...prev, loading: true }));
      
      try {
        // Fetch leads count
        const leadsResponse = await apiService.getLeads();
        const leadsCount = leadsResponse.data ? (Array.isArray(leadsResponse.data) ? leadsResponse.data.length : 0) : 0;
        
        // Fetch campaigns count (total created)
        const campaignsResponse = await apiService.getCampaigns({ page: 1, per_page: 1 });
        const campaignsCount = campaignsResponse.data?.total_items || 0;

        let launchedCampaignsCount = 0;
        let page = 1;
        let totalPages = 1;
        do {
          const pageResponse = await apiService.getCampaigns({ page, per_page: 200 });
          const rows = pageResponse.data?.data || [];
          launchedCampaignsCount += rows.filter((campaign) => {
            const status = (campaign.status || '').toLowerCase();
            return status === 'ongoing' || status === 'completed';
          }).length;
          totalPages = pageResponse.data?.total_pages || 1;
          page += 1;
        } while (page <= totalPages);
        
        // TODO: Fetch sequences when endpoint is available
        const sequencesCount = 0;
        
        setStatistics({
          leadsGenerated: leadsCount,
          campaignsCreated: campaignsCount,
          sequencesCreated: sequencesCount,
          emailsSent: launchedCampaignsCount, // Show count of launched campaigns
          loading: false
        });
      } catch (error) {
        console.error('Error fetching statistics:', error);
        setStatistics(prev => ({ ...prev, loading: false }));
      }
    };

    fetchStatistics();
  }, [user]);

  const getInitials = (name: string) => {
    if (!name) return 'U';
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const handleLogout = async () => {
    try {
      await logout();
      navigate('/auth');
    } catch (error) {
      console.error('Logout error:', error);
      navigate('/auth');
    }
  };

  const handleSaveChanges = async () => {
    try {
      // Send all fields including profile image - empty strings will clear the fields
      // Note: email is completely excluded - it cannot be changed by users
      const response = await apiService.updateUserProfile({
        username: formData.fullName || user?.username,
        // email is intentionally omitted - users cannot change their email
        full_name: formData.fullName,
        department: formData.department,
        location: formData.location,
        website: formData.website,
        bio: formData.bio,
        profile_image: profileImage || undefined, // Send base64 image if available
      });

      if (response.error) {
        toast.error(response.error || 'Failed to update profile');
        return;
      }

      // Refresh user data
      const userResponse = await apiService.getCurrentUser();
      if (userResponse.data) {
        // Update AuthContext user state so the profile header reflects changes
        setUser(userResponse.data);
        
        // Update local form data
        setFormData({
          fullName: userResponse.data.full_name || userResponse.data.username || '',
          email: userResponse.data.email || '',
          department: userResponse.data.department || '',
          location: userResponse.data.location || '',
          website: userResponse.data.website || '',
          bio: userResponse.data.bio || '',
        });
        
        // Update profile image from server response
        setProfileImage(userResponse.data.profile_image || null);
      }

      // Success
      showTopSuccess('Profile updated successfully!');
      
      // Scroll to top of the page
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) {
      console.error('Error updating profile:', error);
      toast.error('Failed to update profile. Please try again.');
    }
  };

  const handleSaveBusinessChanges = async () => {
    if (!companyProfile || !companyProfile.id) {
      toast.error('Company profile not found');
      return;
    }

    try {
      // Convert products_and_services array to the format expected by API
      const productsData = businessFormData.products_and_services.map((item: string) => ({ name: item }));

      const response = await apiService.updateCompany(companyProfile.id, {
        company_name: businessFormData.company_name || undefined,
        company_description: businessFormData.company_description || undefined,
        company_website: businessFormData.company_website || undefined,
        business_email: businessFormData.business_email || undefined,
        state: businessFormData.state || undefined,
        country: businessFormData.country || undefined,
        products_and_services: productsData.length > 0 ? productsData : undefined,
        target_industry: businessFormData.target_industry || undefined,
        target_location: businessFormData.target_location || undefined,
        experience_with_lead_gen_tools: businessFormData.experience_with_lead_gen_tools || undefined,
        lead_generation_expect_monthly: businessFormData.lead_generation_expect_monthly || undefined,
      });

      if (response.error) {
        toast.error(response.error || 'Failed to update business information');
        return;
      }

      // Refresh company profile data
      const companyResponse = await apiService.getMyCompany();
      if (companyResponse.data) {
        setCompanyProfile(companyResponse.data);
        
        // Update form data
        const products = companyResponse.data.products_and_services 
          ? (Array.isArray(companyResponse.data.products_and_services) 
              ? companyResponse.data.products_and_services.map((item: any) => typeof item === 'string' ? item : (item.name || item.title || JSON.stringify(item)))
              : [])
          : [];
        
        setBusinessFormData({
          company_name: companyResponse.data.company_name && companyResponse.data.company_name !== 'N/A' ? companyResponse.data.company_name : '',
          company_description: companyResponse.data.company_description || '',
          company_website: companyResponse.data.company_website || '',
          business_email: companyResponse.data.business_email || '',
          state: companyResponse.data.state || '',
          country: companyResponse.data.country || '',
          products_and_services: products,
          target_industry: companyResponse.data.target_industry && companyResponse.data.target_industry !== 'N/A' ? companyResponse.data.target_industry : '',
          target_location: companyResponse.data.target_location && companyResponse.data.target_location !== 'N/A' ? companyResponse.data.target_location : '',
          experience_with_lead_gen_tools: companyResponse.data.experience_with_lead_gen_tools && companyResponse.data.experience_with_lead_gen_tools !== 'N/A' ? companyResponse.data.experience_with_lead_gen_tools : '',
            lead_generation_expect_monthly: companyResponse.data.lead_generation_expect_monthly && companyResponse.data.lead_generation_expect_monthly !== 'N/A' ? companyResponse.data.lead_generation_expect_monthly : ''
          });

        }

      // Success
      showTopSuccess('Business information updated successfully!');
      
      // Scroll to top of the page
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) {
      console.error('Error updating business information:', error);
      toast.error('Failed to update business information. Please try again.');
    }
  };

  const handleImageUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      // Validate file type - only PNG and JPG
      const validTypes = ['image/png', 'image/jpeg', 'image/jpg'];
      const validExtensions = ['.png', '.jpg', '.jpeg'];
      const fileName = file.name.toLowerCase();
      const fileExtension = fileName.substring(fileName.lastIndexOf('.'));
      
      if (!validTypes.includes(file.type) && !validExtensions.includes(fileExtension)) {
        showTopError('Only PNG and JPG images are allowed');
        return;
      }
      
      // Validate file size (max 5MB)
      if (file.size > 5 * 1024 * 1024) {
        showTopError('Image size should be less than 5MB');
        return;
      }

      // Create preview URL and store base64 for saving
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64Image = reader.result as string;
        setProfileImage(base64Image);
        toast.message('Click Save changes below to keep your profile photo.');
      };
      reader.onerror = () => {
        showTopError('Error reading image file');
      };
      reader.readAsDataURL(file);
    }
  };

  const handleAvatarClick = () => {
    fileInputRef.current?.click();
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString('en-US', { 
        month: '2-digit', 
        day: '2-digit', 
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      });
    } catch {
      return dateString;
    }
  };

  // Validate password meets all requirements
  const validatePassword = (password: string): { isValid: boolean; error: string } => {
    if (password.length < 8) {
      return { isValid: false, error: 'Password must be at least 8 characters' };
    }

    const hasUppercase = /[A-Z]/.test(password);
    const hasLowercase = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecialChar = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password);

    const missingRequirements: string[] = [];
    if (!hasUppercase) missingRequirements.push('uppercase letter');
    if (!hasLowercase) missingRequirements.push('lowercase letter');
    if (!hasNumber) missingRequirements.push('number');
    if (!hasSpecialChar) missingRequirements.push('special character');

    if (missingRequirements.length > 0) {
      let requirementsText = '';
      if (missingRequirements.length === 1) {
        requirementsText = missingRequirements[0];
      } else if (missingRequirements.length === 2) {
        requirementsText = `${missingRequirements[0]} and ${missingRequirements[1]}`;
      } else {
        const last = missingRequirements[missingRequirements.length - 1];
        const rest = missingRequirements.slice(0, -1).join(', ');
        requirementsText = `${rest}, and ${last}`;
      }
      return { 
        isValid: false, 
        error: `Password must include at least one ${requirementsText}` 
      };
    }

    return { isValid: true, error: '' };
  };

  const userName = user?.full_name || user?.username || 'User';
  const userEmail = user?.email || 'user@example.com';
  const userInitials = getInitials(userName);
  
  // Determine user role - check if user has is_superuser or role property
  const userRole = user?.is_superuser || user?.role === 'admin' || user?.role_obj?.name === 'admin' ? 'ADMIN' : 'USER';
  
  // Get first login date (when user first logged in)
  const firstLoginDate = user?.first_login_at || user?.created_at || null;

  return (
    <>
    <div className="user-profile-root-container">
      {/* Hover styles and select dropdown styles are now in UserProfile.css */}

      {/* Main Content */}
      <div className="user-profile-main-content" style={{ flex: 1, overflowY: 'auto' }}>
        {/* User Summary Section - Full Width */}
        <div className="user-profile-content-inner" style={{ maxWidth: '100%', margin: '0 auto' }}>
          {/* Profile Settings - Show if incomplete */}
          {!isLoadingCompany && isCompanyProfileIncomplete && (
            <div style={{ marginBottom: '20px' }}>
              <ProfileSettings
                inline={true}
                existingCompanyData={companyProfile}
                onComplete={() => {
                  // Refresh company profile after completion
                  const checkCompanyProfile = async () => {
                    try {
                      const response = await apiService.getMyCompany();
                      if (response.data) {
                        setCompanyProfile(response.data);
                        setIsCompanyProfileIncomplete(false);
                      }
                    } catch (error) {
                      console.error('Error refreshing company profile:', error);
                    }
                  };
                  checkCompanyProfile();
                }}
              />
            </div>
          )}
          
          {/* Connected Profile Card - Summary + Content as one unified card */}
          <div className="user-profile-summary-card">
            {/* Inner frame for summary: avatar, name, email, department | joined, stats */}
            <div className="user-profile-summary-inner-frame" style={{
              border: '1px solid #E5E7EB',
              borderRadius: '12px',
              padding: '24px',
              backgroundColor: '#FFFFFF',
              marginBottom: '24px',
            }}>
            <div className="responsive-user-header user-profile-summary-centered" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px' }}>
              <div style={{ position: 'relative', flexShrink: 0 }}>
                <div 
                  onClick={handleAvatarClick}
                  className="user-profile-avatar-inline"
                  style={{
                    width: '130px',
                    height: '130px',
                    borderRadius: '50%',
                    backgroundColor: '#A773F6',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    overflow: 'hidden',
                    backgroundImage: profileImage ? `url(${profileImage})` : 'none',
                    backgroundSize: 'cover',
                    backgroundPosition: 'center',
                    backgroundRepeat: 'no-repeat'
                  }}
                >
                  {!profileImage && (
                    <span
                      className={`user-profile-avatar-inline-initials ${userInitials.length <= 1 ? 'user-profile-avatar-inline-initials--one' : 'user-profile-avatar-inline-initials--two'}`}
                    >
                      {userInitials}
                    </span>
                  )}
                </div>
                {/* Camera icon overlay - white circle with purple border and purple camera icon */}
                <div
                  onClick={handleAvatarClick}
                  style={{
                    position: 'absolute',
                    bottom: 0,
                    right: 0,
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    backgroundColor: 'white',
                    border: '1.5px solid #8B5CF6',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)'
                  }}
                >
                  <Camera style={{ width: '12px', height: '12px', color: '#8B5CF6', strokeWidth: 2 }} />
                </div>
                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,.png,.jpg,.jpeg"
                  onChange={handleImageUpload}
                  style={{ display: 'none' }}
                />
              </div>
              <div className="responsive-user-info user-profile-summary-info-centered">
                <div className="user-profile-summary-identity">
                  <div
                    className="responsive-user-name-row user-profile-summary-name-row"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: gap10, flexWrap: 'wrap' }}
                  >
                    <h2 className="user-profile-summary-name">
                      {userName}
                    </h2>
                    {userRole === 'ADMIN' ? (
                      <Badge
                        variant="default"
                        style={{
                          backgroundColor: '#EF4444',
                          color: 'white',
                          fontSize: '10px',
                          fontWeight: 600,
                          padding: '2px 6px',
                        }}
                      >
                        ADMIN
                      </Badge>
                    ) : null}
                  </div>
                  <p className="responsive-user-email user-profile-summary-email">{userEmail}</p>
                </div>
                <div className="responsive-user-meta user-profile-summary-meta">
                  <span className="user-profile-summary-meta-role">
                    {(formData.department || 'Sales Manager').replace(/,\s*$/, '')},
                  </span>
                  <span className="user-profile-summary-meta-divider" aria-hidden="true" />
                  <span className="user-profile-summary-meta-joined">
                    Joined {firstLoginDate ? formatDate(firstLoginDate) : 'N/A'}
                  </span>
                </div>
              </div>
            </div>

            {/* Statistics - small cards, centered */}
            <div className="responsive-stats-grid user-profile-stats-cards" style={{ 
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(163px, 1fr))', 
              gap: '30px',
              marginTop: '16px',
              paddingTop: '16px',
              borderTop: '1px solid #E5E7EB',
              maxWidth: '513px',
              marginLeft: 'auto',
              marginRight: 'auto',
              // Combined border reset for cleanliness
              border: 'none'
            }}>
              <div
                className="responsive-stat-item user-profile-stat-card-item user-profile-stat-metric-card"
                style={{ textAlign: 'center' }}
              >
                <div className="responsive-stat-number user-profile-stat-metric-value">
                  {statistics.loading ? '...' : statistics.leadsGenerated}
                </div>
                <div className="responsive-stat-label user-profile-stat-metric-label">Leads Generated</div>
              </div>
              <div
                className="responsive-stat-item user-profile-stat-card-item user-profile-stat-metric-card"
                style={{ textAlign: 'center' }}
              >
                <div className="responsive-stat-number user-profile-stat-metric-value">
                  {statistics.loading ? '...' : statistics.campaignsCreated}
                </div>
                <div className="responsive-stat-label user-profile-stat-metric-label">Campaigns Created</div>
              </div>
              <div
                className="responsive-stat-item user-profile-stat-card-item user-profile-stat-metric-card"
                style={{ textAlign: 'center' }}
              >
                <div className="responsive-stat-number user-profile-stat-metric-value">
                  {statistics.loading ? '...' : statistics.emailsSent}
                </div>
                <div className="responsive-stat-label user-profile-stat-metric-label">Campaigns Launched</div>
              </div>
            </div>
            </div>
          </div>

          {/* Single Content Card - Tabs + all profile content (connected to profile card above) */}
          <div className="user-profile-content-card" style={{ 
            backgroundColor: 'white', 
            borderRadius: '0 0 18px 18px',
            // maxWidth: 'calc(100% - 48px)'
          }}>
            {/* Single frame: tabs + content inside one bordered area */}
            <div className="user-profile-tabs-frame user-profile-unified-card" style={{
              border: '1px solid #E5E7EB',
              borderRadius: '12px',
              overflow: 'hidden',
              paddingTop: '16px',
              paddingLeft: '16px',
              paddingRight: '16px',
              paddingBottom: '16px',
            }}>
            <Tabs value={activeTab} onValueChange={handleTabChange} style={{ width: '100%' }}>
            <TabsList
              className="user-profile-tabs-list"
              style={{
                marginBottom: '20px',
                marginLeft: 'auto',
                marginRight: 'auto',
              }}
            >
              <TabsTrigger className="user-profile-tabs-trigger" value="profile">
                Profile Information
              </TabsTrigger>
              <TabsTrigger className="user-profile-tabs-trigger" value="business">
                Business Information
              </TabsTrigger>
              <TabsTrigger className="user-profile-tabs-trigger" value="password">
                Password Security
              </TabsTrigger>
              <TabsTrigger className="user-profile-tabs-trigger" value="account">
                Account Information
              </TabsTrigger>
            </TabsList>

            {/* Profile Tab Content */}
            <TabsContent value="profile">
              <div className="user-profile-tab-content-inner" style={{ 
                padding: '0',
                display: 'flex',
                flexDirection: 'column',
                gap: gap16,
              }}>
                {/* Personal Information Section */}
                <div>
                  <Card className="user-profile-card-base user-profile-card-personal-info border-0" style={{ border: 'none', boxShadow: 'none' }}>
                  <CardHeader className="user-profile-card-header-base">
                    <CardTitle className="user-profile-card-title-base">
                      Personal Information
                    </CardTitle>
                    <p className="user-profile-card-desc">
                      Edit your personal information below
                    </p>
                          {/* Divider Line */}
                          <div style={{
                            borderTop: '1px solid #E5E7EB',
                            marginTop: '4px',
                            marginBottom: '4px'
                          }} />
                  </CardHeader>
                  <CardContent>
                    <div className="user-profile-card-content-base" style={{ gap: "14px" }}>
                      {/* First Row: Full Name and Email Address */}
                      <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                        <div>
                          <label className="user-profile-form-label-base">
                            Full Name
                          </label>
                          <Input
                            value={formData.fullName}
                            onChange={(e) => setFormData({ ...formData, fullName: e.target.value })}
                            placeholder="John Smith"
                            className="user-profile-form-input-base"
                          />
                        </div>

                        <div>
                          <label className="user-profile-form-label-base">
                            Email Address
                          </label>
                          <Input
                            type="email"
                            value={user?.email || formData.email}
                            readOnly
                            disabled
                            placeholder="john.smith@company.com"
                            className="user-profile-form-input-base user-profile-form-input-disabled"
                            tabIndex={-1}
                          />
                        </div>
                      </div>

                      {/* Second Row: Department and Location */}
                      <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                        <div>
                          <label className="user-profile-form-label-base">
                            Department
                          </label>
                          <Select 
                            value={formData.department} 
                            onValueChange={(value) => setFormData({ ...formData, department: value })}
                          >
                            <SelectTrigger className="user-profile-form-select-base focus-visible:!ring-0 focus-visible:!ring-transparent">
                              <SelectValue placeholder="Select department" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="Sales">Sales</SelectItem>
                              <SelectItem value="Marketing">Marketing</SelectItem>
                              <SelectItem value="Design">Design</SelectItem>
                              <SelectItem value="Product Management">Product Management</SelectItem>
                              <SelectItem value="Data & Analytics">Data & Analytics</SelectItem>
                              <SelectItem value="Public Relations (PR)">Public Relations (PR)</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        <div>
                          <label className="user-profile-form-label-base">
                            Location
                          </label>
                          <Input
                            value={formData.location}
                            onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                            placeholder="City, Country"
                            className="user-profile-form-input-base"
                          />
                        </div>
                      </div>

                      {/* Website - Full Width */}
                      <div>
                        <label className="user-profile-form-label-base">
                          Website
                        </label>
                        <Input
                          type="url"
                          value={formData.website}
                          onChange={(e) => setFormData({ ...formData, website: e.target.value })}
                          placeholder="https://yourwebsite.com"
                          className="user-profile-form-input-base"
                        />
                      </div>

                      {/* Bio - Full Width */}
                      <div>
                        <label className="user-profile-form-label-base">
                          Bio
                        </label>
                        <Textarea
                          value={formData.bio}
                          onChange={(e) => {
                            const value = e.target.value;
                            // Limit to 160 characters
                            if (value.length <= 160) {
                              setFormData({ ...formData, bio: value });
                            }
                          }}
                          placeholder="Tell us about you"
                          rows={4}
                          maxLength={160}
                            className="user-profile-form-textarea-base"
                        />
                       
                      </div>

                      {/* Save Changes Button */}
                      <div className="user-profile-form-actions" style={{ justifyContent: 'flex-end', marginTop: '40px' }}>
                        <Button
                          onClick={handleSaveChanges}
                          className="user-profile-save-primary"
                        >
                          Save Changes
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
                </div>
              </div>
            </TabsContent>

            {/* Business Information Tab */}
            <TabsContent value="business">
              <div className="user-profile-tab-content-inner" style={{
                padding: '0',
                display: 'flex',
                flexDirection: 'column',
                gap: gap16,
              }}>
                {companyProfile && (
                  <div style={{ paddingBottom: '24px', borderBottom: '1px solid #E5E7EB' }}>
                  <Card className="user-profile-card-base" style={{ border: 'none', boxShadow: 'none' }}>
                    <CardHeader className="user-profile-card-header-base" style={{ paddingBottom: '16px' }}>
                      <CardTitle className="user-profile-card-title-base">
                        Business Information
                      </CardTitle>
                      <p className="user-profile-card-desc">
                        Edit your business information below
                      </p>
                            {/* Divider Line */}
                            <div style={{
                              borderTop: '1px solid #E5E7EB',
                              marginTop: '4px',
                              marginBottom: '4px'
                            }} />
                          </CardHeader>
                        
                          
                    
                          
                    <CardContent className="user-profile-card-content-padding">
                      <div style={{ display: 'flex', flexDirection: 'column', gap: gap16 }}>
                        {/* Company Name and Company Email */}
                        <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                          <div>
                            <label className="user-profile-form-label-base">
                              Company Name
                            </label>
                            <Input
                              value={businessFormData.company_name}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, company_name: e.target.value })}
                              placeholder="Company name"
                              className="user-profile-form-input-base"
                            />
                          </div>
                          <div>
                            <label className="user-profile-form-label-base">
                              Company Email
                            </label>
                            <Input
                              type="email"
                              value={businessFormData.business_email}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, business_email: e.target.value })}
                              placeholder="business@company.com"
                              className="user-profile-form-input-base"
                            />
                          </div>
                        </div>

                        {/* Company Address - State and Country */}
                        <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                          <div>
                            <label className="user-profile-form-label-base">
                              State
                            </label>
                            <Input
                              value={businessFormData.state}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, state: e.target.value })}
                              placeholder="State"
                              className="user-profile-form-input-base"
                            />
                          </div>
                          <div>
                            <label className="user-profile-form-label-base">
                              Country
                            </label>
                            <Input
                              value={businessFormData.country}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, country: e.target.value })}
                              placeholder="Country"
                              className="user-profile-form-input-base"
                            />
                          </div>
                        </div>

                        {/* Description */}
                        <div>
                          <label className="user-profile-form-label-base">
                            Description
                          </label>
                          <Textarea
                            value={businessFormData.company_description}
                            onChange={(e) => setBusinessFormData({ ...businessFormData, company_description: e.target.value })}
                            placeholder="Company description"
                            rows={4}
                            className="user-profile-form-textarea-base"
                          />
                        </div>

                        {/* Website URL */}
                        <div>
                          <label className="user-profile-form-label-base">
                            Website URL
                          </label>
                          <Input
                            type="url"
                            value={businessFormData.company_website}
                            onChange={(e) => setBusinessFormData({ ...businessFormData, company_website: e.target.value })}
                            placeholder="https://example.com"
                            className="user-profile-form-input-base"
                          />
                        </div>

                        {/* Target Industry and Target Location */}
                        <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                          <div>
                            <label className="user-profile-form-label-base">
                              Target Industry
                            </label>
                            <Input
                              value={businessFormData.target_industry}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, target_industry: e.target.value })}
                              placeholder="Target industry"
                              className="user-profile-form-input-base"
                            />
                          </div>
                          <div>
                            <label className="user-profile-form-label-base">
                              Target Location
                            </label>
                            <Input
                              value={businessFormData.target_location}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, target_location: e.target.value })}
                              placeholder="Target location"
                              className="user-profile-form-input-base"
                            />
                          </div>
                        </div>

                        {/* Experience and Expected Monthly Leads */}
                        <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: gap16 }}>
                          <div>
                            <label className="user-profile-form-label-base">
                              Experience with Lead Generation Tools
                            </label>
                            <Input
                              value={businessFormData.experience_with_lead_gen_tools}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, experience_with_lead_gen_tools: e.target.value })}
                              placeholder="Experience level"
                              className="user-profile-form-input-base"
                            />
                          </div>
                          <div>
                            <label className="user-profile-form-label-base">
                              Expected Monthly Leads
                            </label>
                            <Input
                              value={businessFormData.lead_generation_expect_monthly}
                              onChange={(e) => setBusinessFormData({ ...businessFormData, lead_generation_expect_monthly: e.target.value })}
                              placeholder="Expected leads"
                              className="user-profile-form-input-base"
                            />
                          </div>
                        </div>

                        {/* Save Changes Button */}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '40px' }}>
                          <Button
                            onClick={handleSaveBusinessChanges}
                            className="user-profile-save-primary"
                          >
                            Save Changes
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                  </div>
                )}
              </div>
            </TabsContent>

            {/* Account Information Tab */}
            <TabsContent value="account">
              <div className="user-profile-tab-content-inner" style={{
                padding: '0',
                paddingLeft: '0',
              }}>
                <Card className="user-profile-card-base" style={{ border: 'none', boxShadow: 'none' }}>
                  <CardHeader style={{ paddingBottom: '16px' }}>
                    <CardTitle style={{ fontSize: '16px', fontWeight: 600, color: '#111827', margin: 0 }}>
                      Account Information
                    </CardTitle>
                    <p style={{ fontSize: '13px', color: '#A198CE', fontWeight: 400, margin: '4px 0 0 0' }}>
                      See your account information below
                        </p>
                        {/* Divider Line */}
                          <div style={{
                            borderTop: '1px solid #E5E7EB',
                            marginTop: '10px',
                            marginBottom: '24px'
                        }} />
                       
                  </CardHeader>
                  <CardContent className="user-profile-card-content-no-padding">
                    <div
                        style={{
                          display: 'flex',
                          flexDirection: 'row',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                          gap: '40px',
                          width: '100%',
                        }}
                      >
                        <div style={{ paddingTop: '0', flex: 1 }}>
                          <label className="user-profile-form-label-base" style={{ marginBottom: '8px' }}>
                            Account Status
                          </label>
                          <div style={{ paddingTop: '2px', paddingBottom: '20px' }}>
                            <Badge 
                              variant="default"
                              style={{ 
                                backgroundColor: '#8B5CF6', 
                                color: 'white', 
                                fontSize: '11px',
                                fontWeight: 500,
                                padding: '4px 12px',
                                borderRadius: '9999px',
                                border: 'none'
                              }}
                            >
                              active
                            </Badge>
                          </div>
                        </div>

                        <div style={{ flex: 1 }}>
                          <label className="user-profile-form-label-base" style={{ marginBottom: '8px' }}>
                            Last Login
                          </label>
                          <div
                            className="user-profile-account-readonly-value"
                            style={{
                              paddingTop: '2px',
                            }}
                          >
                            {user?.last_login_at ? formatDate(user.last_login_at) : 'Never'}
                          </div>
                        </div>
                      </div>
                      {(() => {
                        const planKey = (billingSubscription?.plan || 'free').toLowerCase();
                        const isPaidPlan =
                          planKey === 'starter' || planKey === 'growth' || planKey === 'scale';
                        const hasStripeCustomer = Boolean(billingSubscription.stripe_customer_id);
                        const cancelAt = billingSubscription.cancel_at;
                        const canOpenPortal = isPaidPlan && hasStripeCustomer;
                        return (
                          <div
                            style={{
                              marginTop: '24px',
                              paddingTop: '24px',
                              borderTop: '1px solid #E5E7EB',
                              width: '100%',
                            }}
                          >
                            <label
                              className="user-profile-form-label-base"
                              style={{ marginBottom: '12px', display: 'block' }}
                            >
                              Subscription &amp; billing
                            </label>
                            {cancelAt ? (
                              <p
                                style={{
                                  fontSize: '13px',
                                  color: '#6B7280',
                                  margin: '0 0 16px 0',
                                  lineHeight: 1.5,
                                }}
                              >
                                Your subscription is set to cancel at the end of the current billing
                                period. You can update payment methods or review invoices in Stripe.
                              </p>
                            ) : null}
                            <div className="user-profile-payment-card">
                              <div className="user-profile-payment-card-text">
                                <div className="user-profile-payment-card-title">Payment</div>
                                <div className="user-profile-payment-card-sub">
                                  Update your payment details, invoices, or cancel your subscription in
                                  Stripe&apos;s secure billing portal.
                                </div>
                              </div>
                              <Button
                                type="button"
                                variant="default"
                                className="user-profile-manage-stripe-btn"
                                disabled={portalLoading || !canOpenPortal}
                                title={
                                  !isPaidPlan
                                    ? 'Subscribe to a paid plan in Plan & usage to manage billing in Stripe.'
                                    : !hasStripeCustomer
                                      ? 'Complete checkout in Plan & usage so this account is linked to Stripe.'
                                      : undefined
                                }
                                onClick={() => void openBillingPortal()}
                              >
                                {portalLoading ? 'Opening…' : 'Manage in Stripe'}
                              </Button>
                            </div>
                            {!isPaidPlan && (
                              <p
                                style={{
                                  fontSize: '12px',
                                  color: '#9CA3AF',
                                  margin: '12px 0 0 0',
                                  lineHeight: 1.45,
                                }}
                              >
                                You are on the free plan. Subscribe in Plan &amp; usage to unlock
                                Stripe billing management here.
                              </p>
                            )}
                            {isPaidPlan && !hasStripeCustomer && (
                              <p
                                style={{
                                  fontSize: '12px',
                                  color: '#9CA3AF',
                                  margin: '12px 0 0 0',
                                  lineHeight: 1.45,
                                }}
                              >
                                Complete billing in Plan &amp; usage so this account is linked to
                                Stripe—then you can open the portal here.
                              </p>
                            )}
                          </div>
                        );
                      })()}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* Password Tab Content */}
            <TabsContent value="password">
              <div className="user-profile-tab-content-inner" style={{
                padding: '0',
                display: 'flex',
                flexDirection: 'column',
                gap: gap16,
              }}>
              <Card className="user-profile-card-base" style={{ border: 'none', boxShadow: 'none' }}>
                <CardHeader className="user-profile-card-header-base">
                  <CardTitle className="user-profile-card-title-base">
                    Change Password
                  </CardTitle>
                  <p className="user-profile-card-desc">
                    Your password must be at least 8 characters and include a mix of uppercase, lowercase, numbers, and special characters.
                  </p>
                        {/* Divider Line */}
                        <div style={{
                          borderTop: '1px solid #E5E7EB',
                          marginTop: '4px',
                          marginBottom: '4px'
                        }} />
                </CardHeader>
                <CardContent className="user-profile-card-content-padding">
                  <div className="user-profile-card-content-base" style={{ gap: gap16 }}>
                    {/* Current Password */}
                    <div>
                      <label className="user-profile-form-label-base">
                        Current Password
                      </label>
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <Input
                          type={showPasswords.current ? 'text' : 'password'}
                          value={passwordData.currentPassword}
                          onChange={(e) => {
                            setPasswordData({ ...passwordData, currentPassword: e.target.value });
                            if (passwordErrors.currentPassword) {
                              setPasswordErrors({ ...passwordErrors, currentPassword: '' });
                            }
                          }}
                          placeholder="Enter current password"
                          className={`user-profile-form-input-base ${passwordErrors.currentPassword ? 'user-profile-form-input-error' : ''}`}
                          style={{ paddingRight: '40px' }}
                        />
                        <button
                          type="button"
                          className="password-toggle-button no-button-effects"
                          onClick={() => setShowPasswords({ ...showPasswords, current: !showPasswords.current })}
                          style={{
                            position: 'absolute',
                            right: '10px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '20px',
                            height: '20px',
                            margin: '0',
                            outline: 'none',
                            boxShadow: 'none'
                          }}
                        >
                          {showPasswords.current ? (
                            <EyeOff style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          ) : (
                            <Eye style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* New Password */}
                    <div>
                      <label className="user-profile-form-label-base">
                        New Password
                      </label>
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <Input
                          type={showPasswords.new ? 'text' : 'password'}
                          value={passwordData.newPassword}
                          onChange={(e) => {
                            setPasswordData({ ...passwordData, newPassword: e.target.value });
                            if (passwordErrors.newPassword) {
                              setPasswordErrors({ ...passwordErrors, newPassword: '' });
                            }
                          }}
                          placeholder="Enter new password"
                          className={`user-profile-form-input-base ${passwordErrors.newPassword ? 'user-profile-form-input-error' : ''}`}
                          style={{ paddingRight: '40px' }}
                        />
                        <button
                          type="button"
                          className="password-toggle-button no-button-effects"
                          onClick={() => setShowPasswords({ ...showPasswords, new: !showPasswords.new })}
                          style={{
                            position: 'absolute',
                            right: '10px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '20px',
                            height: '20px',
                            margin: '0',
                            outline: 'none',
                            boxShadow: 'none'
                          }}
                        >
                          {showPasswords.new ? (
                            <EyeOff style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          ) : (
                            <Eye style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Confirm New Password */}
                    <div>
                      <label className="user-profile-form-label-base">
                        Confirm New Password
                      </label>
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <Input
                          type={showPasswords.confirm ? 'text' : 'password'}
                          value={passwordData.confirmPassword}
                          onChange={(e) => {
                            setPasswordData({ ...passwordData, confirmPassword: e.target.value });
                            if (passwordErrors.confirmPassword) {
                              setPasswordErrors({ ...passwordErrors, confirmPassword: '' });
                            }
                          }}
                          placeholder="Confirm new password"
                          className={`user-profile-form-input-base ${passwordErrors.confirmPassword ? 'user-profile-form-input-error' : ''}`}
                          style={{ paddingRight: '40px' }}
                        />
                        <button
                          type="button"
                          className="password-toggle-button no-button-effects"
                          onClick={() => setShowPasswords({ ...showPasswords, confirm: !showPasswords.confirm })}
                          style={{
                            position: 'absolute',
                            right: '10px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '20px',
                            height: '20px',
                            margin: '0',
                            outline: 'none',
                            boxShadow: 'none'
                          }}
                        >
                          {showPasswords.confirm ? (
                            <EyeOff style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          ) : (
                            <Eye style={{ width: '18px', height: '18px', color: '#A198CE', display: 'block' }} />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: gap12, marginTop: '40px' }}>
                      <Button
                        onClick={() => {
                          // Reset all password fields to empty
                          setPasswordData({ 
                            currentPassword: '', 
                            newPassword: '', 
                            confirmPassword: '' 
                          });
                          // Hide all password visibility toggles
                          setShowPasswords({ 
                            current: false, 
                            new: false, 
                            confirm: false 
                          });
                          // Clear all password errors
                          setPasswordErrors({ 
                            currentPassword: '', 
                            newPassword: '', 
                            confirmPassword: '' 
                          });
                          // Clear any error messages
                          setTopErrorMessage('');
                        }}
                        variant="outline"
                        className="user-profile-back-button-action"
                      >
                        Cancel
                      </Button>
                      <Button
                        onClick={async () => {
                          // Reset errors
                          setPasswordErrors({ currentPassword: '', newPassword: '', confirmPassword: '' });
                          setTopErrorMessage('');

                          // Validate fields
                          if (!passwordData.currentPassword) {
                            setPasswordErrors(prev => ({ ...prev, currentPassword: 'Current password is required' }));
                          showTopError('Current password is required');
                            return;
                          }

                          if (!passwordData.newPassword) {
                            setPasswordErrors(prev => ({ ...prev, newPassword: 'New password is required' }));
                            showTopError('New password is required');
                            return;
                          }

                          // Validate password meets all requirements
                          const passwordValidation = validatePassword(passwordData.newPassword);
                          if (!passwordValidation.isValid) {
                            setPasswordErrors(prev => ({ ...prev, newPassword: passwordValidation.error }));
                            showTopError(passwordValidation.error);
                            return;
                          }

                          if (passwordData.newPassword !== passwordData.confirmPassword) {
                            setPasswordErrors(prev => ({ ...prev, confirmPassword: 'Passwords do not match' }));
                            showTopError('Passwords do not match');
                            return;
                          }

                          try {
                            const response = await apiService.changePassword({
                              current_password: passwordData.currentPassword,
                              new_password: passwordData.newPassword
                            });

                            if (response.error) {
                              // Check if it's a current password error
                              if (response.error.toLowerCase().includes('incorrect') || response.error.toLowerCase().includes('current')) {
                                setPasswordErrors(prev => ({ ...prev, currentPassword: response.error }));
                                showTopError(response.error);
                              } else {
                                showTopError(response.error || 'Failed to change password');
                              }
                              return;
                            }

                            // Success
                            showTopSuccess('Password updated successfully!');
                            setPasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                            setShowPasswords({ current: false, new: false, confirm: false });
                            setPasswordErrors({ currentPassword: '', newPassword: '', confirmPassword: '' });
                            setTopErrorMessage('');
                          } catch (error) {
                            console.error('Error changing password:', error);
                            showTopError('Failed to change password. Please try again.');
                          }
                        }}
                        className="user-profile-save-primary">
                        Update Password
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
              </div>
            </TabsContent>
          </Tabs>
          </div>
          </div>
        </div>
      </div>
    </div>

    {showCancellationFeedbackModal && (
      <div
        className="evecta-dialog-overlay user-profile-cancel-feedback-overlay"
        onClick={() => {
          if (!cancellationFeedbackSubmitting) setShowCancellationFeedbackModal(false);
        }}
        role="presentation"
      >
        <div
          className="evecta-dialog user-profile-cancel-feedback-dialog"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="user-profile-cancel-feedback-title"
        >
          <div className="evecta-dialog-header user-profile-cancel-feedback-header">
            <h2 id="user-profile-cancel-feedback-title" className="evecta-dialog-title">
              Subscription has been canceled
            </h2>
            <button
              type="button"
              className="evecta-dialog-close"
              onClick={() =>
                !cancellationFeedbackSubmitting && setShowCancellationFeedbackModal(false)
              }
              aria-label="Close"
            >
              <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} />
            </button>
          </div>
          <p className="evecta-dialog-description user-profile-cancel-feedback-intro">
            We would love your feedback — tell us why you canceled this subscription. Your access
            continues until the end of the current billing period.
          </p>
          <div className="user-profile-cancel-feedback-reasons" role="radiogroup" aria-label="Cancellation reason">
            {CANCELLATION_FEEDBACK_REASONS.map((r) => (
              <label key={r} className="user-profile-cancel-feedback-radio-row">
                <input
                  type="radio"
                  name="cancellation-reason"
                  value={r}
                  checked={cancellationReason === r}
                  onChange={() => setCancellationReason(r)}
                  disabled={cancellationFeedbackSubmitting}
                />
                <span>{r}</span>
              </label>
            ))}
          </div>
          <label className="user-profile-cancel-feedback-details-label" htmlFor="cancellation-feedback-details">
            Any additional feedback?
          </label>
          <textarea
            id="cancellation-feedback-details"
            className="user-profile-cancel-feedback-textarea"
            rows={3}
            placeholder="Any additional feedback?"
            value={cancellationDetails}
            onChange={(e) => setCancellationDetails(e.target.value)}
            disabled={cancellationFeedbackSubmitting}
          />
          <div className="evecta-dialog-actions user-profile-cancel-feedback-actions">
            <button
              type="button"
              onClick={() => setShowCancellationFeedbackModal(false)}
              disabled={cancellationFeedbackSubmitting}
              className="evecta-dialog-btn evecta-dialog-btn--secondary"
            >
              No thanks
            </button>
            <button
              type="button"
              onClick={() => void submitCancellationFeedback()}
              disabled={cancellationFeedbackSubmitting}
              className="evecta-dialog-btn evecta-dialog-btn--primary"
            >
              {cancellationFeedbackSubmitting ? 'Sending…' : 'Submit'}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
