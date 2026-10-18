import { useState, useEffect, useRef } from 'react';
import { Search, FileText, Users, Eye, Copy, Edit, Trash2, Filter, ChevronDown, X, Save, Plus, MoreHorizontal } from 'lucide-react';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs';
import { Button } from '../ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { apiService, EmailTemplate } from '../../../../shared/services/api';
import { toast } from 'sonner';
import { useMobileGap } from '../ui/use-mobile-gap';
import { useIsMobile } from '../ui/use-mobile';
import '../LeadLog/LeadLog.css';
import '../Inbox/Inbox.css';
import '../ui/EmptyState.css';
import './Template.css';

interface TemplateCard {
  id: string;
  name: string;
  description: string;
  tags: string[];
  usageCount: number;
  isFavorite: boolean;
  subject: string;
  content: string;
  category?: 'professional' | 'value-proposition' | 'network-outreach';
}

interface TemplateProps {
  onToggleSidebar?: () => void;
}

/** Default system template names – delete button is hidden for these. Only these three are kept. */
const DEFAULT_TEMPLATE_NAMES = ['Professional', 'Network Outreach', 'Value Proportion'];

function isDefaultTemplateByName(name: string): boolean {
  return DEFAULT_TEMPLATE_NAMES.some(
    (defaultName) => (name || '').trim().toLowerCase() === defaultName.toLowerCase()
  );
}

function isDefaultTemplate(template: TemplateCard): boolean {
  return isDefaultTemplateByName(template.name);
}

interface TemplateCardProps {
  template: TemplateCard;
  onEdit: (template: TemplateCard) => void;
  onCopy: (template: TemplateCard) => void;
  onDelete: (id: string) => void;
  onView: (templateId: string) => void;
  getTagColor: (tag: string) => string;
  getTopBorderColor: (template: TemplateCard) => string;
  showDelete?: boolean;
}

function TemplateCardComponent({ 
  template, 
  onEdit, 
  onCopy, 
  onDelete,
  onView,
  getTagColor,
  getTopBorderColor,
  showDelete = true
}: TemplateCardProps) {
  // Mobile gap helpers
  const gap4 = useMobileGap(4);
  const gap6 = useMobileGap(6);
  const gap8 = useMobileGap(8);
  const gap12 = useMobileGap(12);
  const isMobile = useIsMobile();
  
  const [isHovered, setIsHovered] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

  const handleCardClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (
      target.closest('button') ||
      target.closest('[role="button"]') ||
      target.closest('.template-card-menu-dropdown')
    ) {
      return;
    }
    onView(template.id);
  };

  return (
    <div
      onClick={handleCardClick}
      className={`template-card-base ${isHovered ? 'template-card-hovered' : ''}`}
      style={{
        gap: gap8
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Header - Title only, no icon */}
      <div className="template-card-header" style={{ gap: gap8, display: 'flex', alignItems: 'center' }}>
        <h3 className="template-card-title" style={{ margin: 0, padding: 0, display: 'flex', alignItems: 'center', lineHeight: '1' }}>
          {template.name}
        </h3>
      </div>

      {/* Template Description with three-dots menu inline */}
      <div className="template-card-description-row" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: gap8, width: '100%' }}>
        <p className="template-card-description" style={{ flex: 1, minWidth: 0 }}>
          {(() => {
            const desc = template.description;
            const ideaForIdx = desc.indexOf(' idea for ');
            if (ideaForIdx !== -1) {
              const firstLine = desc.slice(0, ideaForIdx).trim();
              const secondLine = desc.slice(ideaForIdx + 1).trimStart();
              return (
                <>
                  {firstLine}
                  <br />
                  {secondLine}
                </>
              );
            }
            const braceIdx = desc.indexOf('{{');
            if (braceIdx !== -1) {
              const firstLine = desc.slice(0, braceIdx).trim();
              const secondLine = desc.slice(braceIdx);
              return (
                <>
                  {firstLine}
                  <br />
                  {secondLine}
                </>
              );
            }
            return desc;
          })()}
        </p>
        <div
          ref={menuRef}
          style={{ flexShrink: 0, position: 'relative' }}
        >
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
            className="template-card-menu-trigger"
            style={{
              background: 'white',
              border: '1px solid #E5E7EB',
              outline: 'none',
              borderRadius: '50%',
              cursor: 'pointer',
              padding: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 32,
              height: 32,
              transition: 'background-color 0.2s'
            }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'white'; }}
          >
            <MoreHorizontal style={{ height: 16, width: 16, color: '#6B7280' }} />
          </button>
          {menuOpen && (
            <div className="template-card-menu-dropdown" style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: 4,
              background: 'white',
              border: '1px solid #E5E7EB',
              borderRadius: 8,
              boxShadow: 'none',
              width: 'max-content',
              zIndex: 50,
              overflow: 'hidden'
            }}>
              <button
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onEdit(template); }}
                className="template-card-menu-item"
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'Urbanist', fontSize: 13, color: '#111827', textAlign: 'left' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                <Edit style={{ height: 14, width: 14, flexShrink: 0 }} />
                Edit
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onCopy(template); }}
                className="template-card-menu-item"
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'Urbanist', fontSize: 13, color: '#111827', textAlign: 'left' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                <Copy style={{ height: 14, width: 14, flexShrink: 0 }} />
                Copy
              </button>
              {showDelete && (
                <button
                  onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onDelete(template.id); }}
                  className="template-card-menu-item evecta-destructive-menu-item"
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'Urbanist', fontSize: 13, textAlign: 'left', width: '100%' }}
                >
                  <Trash2 style={{ height: 14, width: 14, flexShrink: 0 }} />
                  Delete
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tags Section — 2-column grid; left #9164FF, right #A198CE */}
      <div className="template-card-tags-section">
        <div className="template-card-tags-label">Tags:</div>
        <div className="template-card-tags-container template-card-tags-grid">
          {template.tags.map((tag, index) => (
            <span
              key={index}
              className={`template-card-tag ${index % 2 === 0 ? 'template-card-tag-primary' : 'template-card-tag-secondary'}`}
            >
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className="template-card-usage-row">
        <Users className="template-card-usage-icon" aria-hidden />
        <span className="template-card-usage-text">
          Usage Count: {template.usageCount}
        </span>
      </div>
    </div>
  );
}

export function Template({ onToggleSidebar }: TemplateProps) {
  // Mobile detection
  const isMobile = useIsMobile();
  
  // Mobile gap helpers
  const gap4 = useMobileGap(4);
  const gap5 = useMobileGap(5);
  const gap6 = useMobileGap(6);
  const gap8 = useMobileGap(8);
  const gap10 = useMobileGap(10);
  const gap12 = useMobileGap(12);
  const gap16 = useMobileGap(16);
  const gap24 = useMobileGap(24);
  
  const [templates, setTemplates] = useState<TemplateCard[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'library' | 'favorites'>('library');
  const [filterValue, setFilterValue] = useState('all');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateCard | null>(null);
  const [editingTemplate, setEditingTemplate] = useState<TemplateCard | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [templateToDelete, setTemplateToDelete] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTemplate, setNewTemplate] = useState({
    name: '',
    category: 'professional' as TemplateCard['category'],
    subject: '',
    content: '',
    tags: [] as string[]
  });
  const [tagInput, setTagInput] = useState('');
  const editSubjectRef = useRef<HTMLDivElement>(null);
  const editContentRef = useRef<HTMLDivElement>(null);
  // Initialize with default categories so dropdown shows items immediately
  const [categories, setCategories] = useState<Array<{ value: string; label: string }>>([
    { value: 'professional', label: 'Professional' },
   
    { value: 'value-proposition', label: 'Value Proposition' },
    { value: 'network-outreach', label: 'Network Outreach' },
   
  ]);

  // Fetch templates and categories from API
  useEffect(() => {
    fetchTemplates();
    fetchCategories();
  }, []);

  const fetchTemplates = async () => {
    setIsLoading(true);
    try {
      // Fetch templates and usage stats in parallel
      const [templatesResponse, usageStatsResponse] = await Promise.allSettled([
        apiService.getEmailTemplates(),
        apiService.getEmailTemplateUsageStats()
      ]);

      // Get usage stats if available
      let usageStats: { [templateId: string]: number } = {};
      if (usageStatsResponse.status === 'fulfilled' && usageStatsResponse.value.data) {
        usageStats = usageStatsResponse.value.data;
      }

      // Debug logging
      console.log('Templates response status:', templatesResponse.status);
      if (templatesResponse.status === 'fulfilled') {
        console.log('Templates response value:', templatesResponse.value);
        console.log('Templates response data:', templatesResponse.value.data);
        console.log('Is data an array?', Array.isArray(templatesResponse.value.data));
      } else {
        console.error('Templates response rejected:', templatesResponse.reason);
      }

      if (templatesResponse.status === 'fulfilled') {
        const response = templatesResponse.value;
        
        // Check if there's an error in the response
        if (response.error) {
          console.error('API returned error:', response.error);
          toast.error(`Failed to load templates: ${response.error}`);
          setTemplates([]);
          return;
        }
        
        // Check if data exists
        if (!response.data) {
          console.warn('API response has no data field');
          setTemplates([]);
          return;
        }
        
        const templatesData = response.data;
        
        // Check if data is an array
        if (!Array.isArray(templatesData)) {
          console.error('Templates data is not an array:', templatesData, 'Type:', typeof templatesData);
          setTemplates([]);
          return;
        }
        
        if (templatesData.length > 0) {
          // Map API response to TemplateCard format
          // Only auto-generate tags for default system templates; user-created templates show no tags unless the user added them
          const mappedTemplates: TemplateCard[] = templatesData.map((template: EmailTemplate) => ({
            id: template.id,
            name: template.name,
            description: template.subject || `Template: ${template.name}`,
            tags: isDefaultTemplateByName(template.name) ? extractTags(template.content, template.category, template.name) : [],
            usageCount: template.usage_count || usageStats[template.id] || 0, // Use API usage_count, or stats, or default to 0
            isFavorite: template.is_favorite || false, // Load favorite status from backend
            subject: template.subject,
            content: template.content,
            category: template.category // Use category from backend
          }));
          console.log('Successfully loaded templates:', mappedTemplates.length);
          setTemplates(mappedTemplates);
        } else {
          // No templates from backend - set empty array
          console.log('No templates found in response (empty array)');
          setTemplates([]);
        }
      } else {
        // Promise was rejected
        const errorMsg = templatesResponse.reason?.message || templatesResponse.reason || 'Unknown error';
        console.error('Failed to fetch templates (promise rejected):', templatesResponse.reason);
        toast.error(`Failed to load templates: ${errorMsg}`);
        setTemplates([]);
      }
    } catch (error) {
      console.error('Failed to fetch templates:', error);
      toast.error(`Failed to load templates: ${error instanceof Error ? error.message : 'Unknown error'}`);
      // Don't use mock data - just set empty array
      setTemplates([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Extract tags from template content and category (enhanced implementation)
  const extractTags = (content: string, category?: string, name?: string): string[] => {
    const tags: string[] = [];
    const contentLower = content.toLowerCase();
    const nameLower = name?.toLowerCase() || '';
    
    // Add tags based on category
    if (category === 'professional') {
      tags.push('introduction', 'professional');
      if (contentLower.includes('collaboration') || contentLower.includes('partnership')) {
        tags.push('collaboration', 'partnership');
      }
    } else if (category === 'value-proposition') {
      tags.push('sales', 'value-proposition');
      if (contentLower.includes('roi') || contentLower.includes('cost') || contentLower.includes('saving')) {
        tags.push('roi', 'cost-savings');
      }
      if (contentLower.includes('case') || contentLower.includes('study')) {
        tags.push('case-study');
      }
    } else if (category === 'network-outreach') {
      tags.push('networking');
      if (contentLower.includes('follow') || contentLower.includes('follow-up')) {
        tags.push('follow-up');
      }
      if (contentLower.includes('relationship') || contentLower.includes('building')) {
        tags.push('relationship-building');
      }
      if (contentLower.includes('industry')) {
        tags.push('industry');
      }
      // Add two more default tags for network-outreach
      if (!tags.includes('connection')) {
        tags.push('connection');
      }
      if (!tags.includes('outreach')) {
        tags.push('outreach');
      }
    }
    
    // Add tags based on content keywords
    const commonTags = ['introduction', 'professional', 'networking', 'value-proposition', 'case-studies', 'closing', 'respectful', 'collaboration', 'partnership', 'follow-up', 'sales', 'roi', 'cost-savings', 'relationship-building', 'industry', 'connection', 'outreach'];
    commonTags.forEach(tag => {
      if (!tags.includes(tag) && contentLower.includes(tag.replace('-', ' ')) && tags.length < 4) {
        tags.push(tag);
      }
    });
    
    // If no tags found, add default based on name
    if (tags.length === 0) {
      if (nameLower.includes('follow')) {
        tags.push('follow-up');
      } else if (nameLower.includes('value') || nameLower.includes('proposition')) {
        tags.push('value-proposition', 'sales');
      } else if (nameLower.includes('network')) {
        tags.push('networking');
      } else if (nameLower.includes('professional') || nameLower.includes('introduction')) {
        tags.push('introduction', 'professional');
      } else {
        tags.push('professional');
      }
    }
    
    // Ensure at least one tag
    if (tags.length === 0) {
      tags.push('professional');
    }
    
    return tags.slice(0, 4); // Return max 4 tags
  };

  // Mock templates for demo
  const getMockTemplates = (): TemplateCard[] => [
    {
      id: '1',
      name: 'Professional',
      description: 'Introduction from [Your Business Name]',
      tags: ['introduction', 'professional', 'collaboration', 'partnership'],
      usageCount: 45,
      isFavorite: true,
      subject: 'Exploring a Strategic Alignment with {{business_name}}',
      content: `Hello!

Greetings,

It's always inspiring to see how {{Business name}} continues to shape the {{industry}} space. The clarity of your initiatives and the pace of execution reflect a team that knows exactly where the market is moving.

Based on what we've been building, we see a potential strategic alignment that could create value for both sides, not in a broad sense, but in particular areas where our strengths complement each other. We would like to briefly outline these intersections and explore whether collaboration could support your upcoming initiatives.

If you're open to it, a focused 15-minute conversation would be enough to determine whether it's worth moving forward. We are flexible and can adjust to a time that best suits your schedule.

With warm regards,

[Your Name]

{{senderEmail}}

{{senderPhone}}`,
      category: 'professional'
    },
   
    {
      id: '2',
      name: 'Network Outreach',
      description: 'Connecting with fellow {{industry}} professionals',
      tags: ['networking', 'follow-up', 'value-proposition', 'case-studies'],
      usageCount: 15,
      isFavorite: true,
      subject: 'Connecting with fellow {{industry}} professionals',
      content: `Hi {{BusinessName}} Team,

Looking at how different teams are adapting to shifts in the {{industry}} landscape, {{BusinessName}} caught my attention for the strength and precision of your recent initiatives.

I'd like to connect and exchange insights, as we collaborate with organizations facing similar challenges in this sector. A brief introductory conversation could help us explore whether there's any meaningful alignment.

If you're open to it, I'd appreciate the chance to connect briefly and exchange insights. A quick coffee chat or short virtual meeting works perfectly.

Looking forward to connecting,

Best regards,

[Your Business Name]`,
      category: 'network-outreach'
    },
   
    {
      id: '3',
      name: 'Value Proportion',
      description: 'Showcasing our value proposition to {{business_name}}',
      tags: ['value-proposition', 'professional', 'case-studies'],
      usageCount: 30,
      isFavorite: false,
      subject: 'Value proposition for {{business_name}}',
      content: `Hello Team,

While exploring standout organizations in the {{industry}} space, {{Business name}} consistently stood out. The pace and quality of your recent growth truly reflect strong leadership and a clear operational vision.

Given your role, I thought you might be interested in some of the operational gains companies in your segment have been achieving through targeted optimization. For example, similar organizations recently saw:

 • 30% reduction in operational costs

 • 50% faster processing across key workflows

 • 95% accuracy improvements in routine tasks

What's notable is that these improvements were achieved without major restructuring—just smarter systems and refined processes.

If it's helpful, I'd be glad to walk you through the approach in a quick 10-minute conversation and share how these results could translate to {{Business name}}.

Best regards,

[Your Business Name]`,
      category: 'value-proposition'
    }
  ];

  const toggleFavorite = async (templateId: string) => {
    try {
      // Optimistically update UI
      setTemplates(prev => 
        prev.map(template => 
          template.id === templateId 
            ? { ...template, isFavorite: !template.isFavorite }
            : template
        )
      );

      // Update selected template if it's the one being toggled
      if (selectedTemplate && selectedTemplate.id === templateId) {
        setSelectedTemplate(prev => prev ? { ...prev, isFavorite: !prev.isFavorite } : null);
      }

      // Call API to save favorite status
      const response = await apiService.toggleTemplateFavorite(templateId);
      
      if (response.data) {
        // Update with server response to ensure consistency
        setTemplates(prev => 
          prev.map(template => 
            template.id === templateId 
              ? { ...template, isFavorite: response.data.is_favorite || false }
              : template
          )
        );

        // Update selected template if it's the one being toggled
        if (selectedTemplate && selectedTemplate.id === templateId) {
          setSelectedTemplate(prev => prev ? { ...prev, isFavorite: response.data.is_favorite || false } : null);
        }
      }
    } catch (error) {
      console.error('Failed to toggle favorite:', error);
      toast.error('Failed to update favorite status');
      
      // Revert optimistic update on error
      setTemplates(prev => 
        prev.map(template => 
          template.id === templateId 
            ? { ...template, isFavorite: !template.isFavorite }
            : template
        )
      );

      if (selectedTemplate && selectedTemplate.id === templateId) {
        setSelectedTemplate(prev => prev ? { ...prev, isFavorite: !prev.isFavorite } : null);
      }
    }
  };

  const handleDelete = (templateId: string) => {
    setTemplateToDelete(templateId);
    setShowDeleteConfirm(true);
  };

  const confirmDelete = async () => {
    if (templateToDelete) {
      // Check if template ID is a valid UUID (from backend) or a mock ID
      const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(templateToDelete);

      try {
        if (isUUID) {
          // Real template from backend - delete via API
          await apiService.deleteEmailTemplate(templateToDelete);
        }
        // Update local state for both real and mock templates
        setTemplates(prev => prev.filter(t => t.id !== templateToDelete));
        toast.success('Template deleted successfully');
        setShowDeleteConfirm(false);
        setTemplateToDelete(null);
        // Close sidebar if the deleted template was selected
        if (selectedTemplate?.id === templateToDelete) {
          setSelectedTemplate(null);
        }
      } catch (error) {
        console.error('Failed to delete template:', error);
        toast.error('Failed to delete template');
      }
    }
  };

  const cancelDelete = () => {
    setShowDeleteConfirm(false);
    setTemplateToDelete(null);
  };

  const handleCopy = async (template: TemplateCard) => {
    try {
      // Copy the full email content including subject
      const contentToCopy = `Subject: ${template.subject}\n\n${template.content || template.description}`;
      await navigator.clipboard.writeText(contentToCopy);
      toast.success('Email content copied to clipboard');
    } catch (error) {
      console.error('Failed to copy:', error);
      toast.error('Failed to copy to clipboard');
    }
  };

  const handleEdit = (template: TemplateCard) => {
    setEditingTemplate(template);
  };

  const handleSaveEdit = async () => {
    if (!editingTemplate) return;

    // Check if template ID is a valid UUID (from backend) or a mock ID
    const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(editingTemplate.id);

    try {
      if (isUUID) {
        // Real template from backend - update via API
        await apiService.updateEmailTemplate(editingTemplate.id, {
          name: editingTemplate.name,
          subject: editingTemplate.subject,
          content: editingTemplate.content
        });
      }
      // Update local state for both real and mock templates
      setTemplates(prev => 
        prev.map(t => t.id === editingTemplate.id ? editingTemplate : t)
      );
      // Update selected template if it's the one being edited
      if (selectedTemplate?.id === editingTemplate.id) {
        setSelectedTemplate(editingTemplate);
      }
      setEditingTemplate(null);
      toast.success('Template updated successfully');
    } catch (error) {
      console.error('Failed to update template:', error);
      toast.error('Failed to update template');
    }
  };

  const handleCancelEdit = () => {
    setEditingTemplate(null);
  };

  const handleView = (templateId: string) => {
    const template = templates.find(t => t.id === templateId);
    if (template) {
      setSelectedTemplate(template);
    }
  };

  const handleCloseSidebar = () => {
    setSelectedTemplate(null);
  };

  // When Edit Template modal opens, fill contentEditables with highlighted content
  useEffect(() => {
    if (!editingTemplate) return;
    const apply = () => {
      if (editSubjectRef.current) {
        editSubjectRef.current.innerHTML = highlightTemplateVariables(editingTemplate.subject || '');
      }
      if (editContentRef.current) {
        editContentRef.current.innerHTML = highlightTemplateVariables(editingTemplate.content || '');
      }
    };
    const id = setTimeout(apply, 0);
    return () => clearTimeout(id);
  }, [editingTemplate?.id]);

  const handleAddTag = () => {
    if (tagInput.trim() && !newTemplate.tags.includes(tagInput.trim())) {
      setNewTemplate({
        ...newTemplate,
        tags: [...newTemplate.tags, tagInput.trim()]
      });
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setNewTemplate({
      ...newTemplate,
      tags: newTemplate.tags.filter(tag => tag !== tagToRemove)
    });
  };

  const handleCreateTemplate = async () => {
    // Validate required fields
    if (!newTemplate.name.trim() || !newTemplate.subject.trim() || !newTemplate.content.trim()) {
      toast.error('Please fill in all required fields');
      return;
    }

    try {
      const response = await apiService.createEmailTemplate({
        name: newTemplate.name.trim(),
        subject: newTemplate.subject.trim(),
        content: newTemplate.content.trim(),
        category: newTemplate.category
      });

      if (response.data) {
        toast.success('Template created successfully');
        // Reset form
        setNewTemplate({
          name: '',
          category: 'professional',
          subject: '',
          content: '',
          tags: []
        });
        setTagInput('');
        setShowCreateModal(false);
        // Refresh templates list
        fetchTemplates();
      } else {
        toast.error(response.error || 'Failed to create template');
      }
    } catch (error) {
      console.error('Failed to create template:', error);
      toast.error('Failed to create template');
    }
  };

  const handleCancelCreate = () => {
    setShowCreateModal(false);
    setNewTemplate({
      name: '',
      category: 'professional',
      subject: '',
      content: '',
      tags: []
    });
    setTagInput('');
  };

  // Count templates by category
  const getCategoryCount = (category: string): number => {
    const count = templates.filter(template => {
      // Use category from backend if available
      if (template.category) {
        return template.category === category;
      }
      
      // If template has no category, don't count it in any category
      // (only count templates that explicitly have a category assigned)
      return false;
    }).length;
    
    return count;
  };

  // Filter templates
  const filteredTemplates = templates.filter(template => {
    const matchesSearch = 
      template.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      template.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      template.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()));
    
    const matchesTab = activeTab === 'library' || template.isFavorite;
    
    // Filter by category
    let matchesCategory = true;
    if (filterValue && filterValue !== 'all') {
      // Use category from backend if available
      if (template.category) {
        matchesCategory = template.category === filterValue;
      } else {
        // Fallback to name/tag matching for templates without category
        const nameLower = template.name.toLowerCase();
        const tagsLower = template.tags.map(t => t.toLowerCase());
        
        switch (filterValue) {
          case 'professional':
            matchesCategory = nameLower.includes('professional');
            break;
         
          case 'value-proposition':
            matchesCategory = tagsLower.includes('value-proposition') || nameLower.includes('value');
            break;
          case 'network-outreach':
            matchesCategory = nameLower.includes('networking') || nameLower.includes('network outreach');
            break;
         
          default:
            matchesCategory = true;
        }
      }
    }
    
    return matchesSearch && matchesTab && matchesCategory;
  });

  const favoriteCount = templates.filter(t => t.isFavorite).length;
  const totalTemplates = templates.length;

  // Fetch categories from backend
  const fetchCategories = async () => {
    try {
      const response = await apiService.getEmailTemplateCategories();
      console.log('Categories response:', response); // Debug log
      if (response.data && response.data.length > 0) {
        setCategories(response.data);
      } else {
        console.warn('Categories response is empty, using defaults');
      }
    } catch (error) {
      console.error('Failed to fetch categories:', error);
      // Keep default categories if API fails
    }
  };

  // Get category display name
  const getCategoryDisplayName = (category: string): string => {
    const categoryInfo = categories.find(cat => cat.value === category);
    return categoryInfo ? categoryInfo.label : category;
  };

  // Helper function to highlight variables in template content with colors
  const highlightTemplateVariables = (text: string): string => {
    if (!text) return '';
    
    // Escape HTML to prevent XSS
    const escapeHtml = (str: string) => {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    };
    
    // Start with escaped text; preserve line breaks for content
    let highlighted = escapeHtml(text);
    highlighted = highlighted.replace(/\n/g, '<br>');
    
    // First, highlight square bracket placeholders (e.g., [Your Name], [Company Name])
    const placeholderColor = '#6B21A8'; // Purple
    const placeholderRegex = /\[([^\]]+)\]/g;
    highlighted = highlighted.replace(
      placeholderRegex,
      `<span style="color: ${placeholderColor}; font-weight: 600; background-color: #F3E8FF; padding: 2px 4px; border-radius: 3px;">[$1]</span>`
    );
    
    // Variable colors (match CampaignEmailScreen: business_name orange, industry blue, address green)
    const variableColors: { [key: string]: string } = {
      '{{business_name}}': '#D97706',
      '{{ business_name }}': '#D97706',
      '{{industry}}': '#3B82F6',
      '{{ industry }}': '#3B82F6',
      '{{address}}': '#059669',
      '{{ address }}': '#059669',
      '{{location}}': '#10B981',
      '{{ location }}': '#10B981',
      '{{first_name}}': '#EC4899',
      '{{ first_name }}': '#EC4899'
    };
    
    Object.keys(variableColors).forEach(variable => {
      const regex = new RegExp(variable.replace(/[{}]/g, '\\$&'), 'gi');
      highlighted = highlighted.replace(
        regex,
        `<span style="color: ${variableColors[variable]}; font-weight: 500;">${variable}</span>`
      );
    });
    
    return highlighted;
  };

  // Get plain text from contentEditable preserving line breaks (for Edit modal content field)
  const getEditContentText = (el: HTMLElement | null): string => {
    if (!el) return '';
    const html = el.innerHTML || '';
    const withNewlines = html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/div>\s*/gi, '\n')
      .replace(/<div[^>]*>/gi, '')
      .replace(/<\/p>\s*/gi, '\n')
      .replace(/<p[^>]*>/gi, '');
    const div = document.createElement('div');
    div.innerHTML = withNewlines;
    return div.textContent || div.innerText || '';
  };

  // Tag color mapping
  const getTagColor = (tag: string): string => {
    const colorMap: { [key: string]: string } = {
      'introduction': '#3B82F6', // blue
      'follow-up': '#10B981', // green
      'sales': '#A855F7', // purple
      'networking': '#FBBF24', // yellow
      'closing': '#EF4444', // red
      'professional': '#F97316', // orange
      'collaboration': '#F97316', // orange
      'partnership': '#F97316', // orange
      'value-proposition': '#F97316', // orange
      'case-studies': '#F97316', // orange
      'respectful': '#F97316' // orange
    };
    return colorMap[tag] || '#6B7280';
  };

  // Get top border color based on primary tag or category
  const getTopBorderColor = (template: TemplateCard): string => {
    if (template.tags.length > 0) {
      return getTagColor(template.tags[0]);
    }
    // Fallback to category-based colors
    if (template.category === 'professional') return '#3B82F6'; // blue
    if (template.category === 'value-proposition') return '#A855F7'; // purple
    if (template.category === 'network-outreach') return '#FBBF24'; // yellow
    return '#6B7280'; // default gray
  };

  return (
    <div className="template-main-container">
      {/* Main Content Area */}
      <div className="template-content-container">
      {/* Header — toolbar with Inbox-style search */}
      <div className="template-header-container-mobile template-header-container-base" style={{
        display: 'flex',
        flexDirection: 'column',
        padding: '12px 16px 0 16px',
        flexShrink: 0
      }}>
        {/* Search + filters — outer bar + search field match Inbox */}
        <div style={{ marginBottom: '16px', flexShrink: 0, paddingTop: '8px', width: '100%' }}>
          <div className="inbox-search-filters template-page-toolbar">
            <div className="inbox-search-filter-container">
              <div className="inbox-search-refresh-wrapper">
                <div className="inbox-search-input-container">
                  <Search className="inbox-search-icon" aria-hidden />
                  <Input
                    type="text"
                    placeholder="Search here..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="inbox-search-input"
                  />
                </div>
              </div>
            </div>
            <div className="template-toolbar-actions">
            {/* Filter */}
            <div className="lead-log-industry-filter" style={{ flexShrink: 0 }}>
              <Select value={filterValue} onValueChange={setFilterValue}>
                <SelectTrigger
                  className="template-filter-trigger-mobile"
                  style={{
                    height: '36px',
                    minWidth: '220px',
                    width: 'auto',
                    border: '1px solid #E5E7EB',
                    backgroundColor: '#FFFFFF',
                    borderRadius: '6px',
                    fontSize: '12px',
                    fontWeight: 500,
                    color: '#111827',
                    fontFamily: 'Urbanist, sans-serif',
                    display: 'flex',
                    alignItems: 'center',
                    gap: gap8,
                    flexShrink: 0,
                    margin: 0,
                    paddingLeft: '10px',
                    paddingRight: '10px',
                    lineHeight: '1',
                    boxShadow: 'none'
                  }}
                >
                  <Filter style={{ height: 16, width: 16, color: '#6B7280', flexShrink: 0 }} />
                  <SelectValue style={{ display: 'flex', alignItems: 'center', lineHeight: '1' }}>
                    {filterValue === 'all'
                      ? `All Templates Category(${totalTemplates})`
                      : getCategoryDisplayName(filterValue)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Templates Category</SelectItem>
                  {categories && categories.length > 0 ? (
                    categories.map((category) => (
                      <SelectItem key={category.value} value={category.value}>
                        {category.label}
                      </SelectItem>
                    ))
                  ) : (
                    <>
                      <SelectItem value="professional">Professional</SelectItem>
                      <SelectItem value="value-proposition">Value Proposition</SelectItem>
                      <SelectItem value="network-outreach">Network Outreach</SelectItem>
                    </>
                  )}
                </SelectContent>
              </Select>
            </div>
            {/* New Template — same shell as Create Campaign (.evecta-primary-btn) */}
            <Button
              variant="default"
              onClick={() => setShowCreateModal(true)}
              className="lead-log-create-campaign-btn shrink-0"
            >
              New Template
            </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div style={{ 
        flex: '1 1 0%',
        overflowY: 'auto',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: gap16
      }}>
        {/* Template Cards Grid */}
        {isLoading ? (
          <div style={{ 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center', 
            height: '200px',
            color: '#6B7280',
            fontFamily: 'Urbanist'
          }}>
            Loading templates...
          </div>
        ) : filteredTemplates.length === 0 ? (
          <div className="template-empty-state">
            <FileText className="template-empty-state-icon" strokeWidth={1.25} aria-hidden />
            <p className="dashboard-empty-state-title">No templates found.</p>
            <p className="dashboard-empty-state-description">
              Create your first template to get started.
            </p>
          </div>
        ) : (
          <div className="template-grid-container">
            {filteredTemplates.map((template) => (
              <TemplateCardComponent
                key={template.id}
                template={template}
                onEdit={handleEdit}
                onCopy={handleCopy}
                onDelete={handleDelete}
                onView={handleView}
                getTagColor={getTagColor}
                getTopBorderColor={getTopBorderColor}
                showDelete={!isDefaultTemplate(template)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Right Side Detail Panel - click outside to close */}
      {selectedTemplate && (
        <div className="template-detail-panel-wrapper" style={{ position: 'fixed', inset: 0, zIndex: 100 }}>
          <div
            className="template-detail-panel-backdrop"
            style={{ position: 'absolute', inset: 0, cursor: 'default' }}
            onClick={handleCloseSidebar}
            aria-hidden="true"
          />
          <div className="template-detail-panel-container" style={{
            position: 'fixed',
            right: 0,
            top: 0,
            bottom: 0,
            width: '30%',
            minWidth: '250px',
            maxWidth: '350px',
            backgroundColor: 'white',
            borderLeft: '1px solid #E5E7EB',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '-2px 0 8px rgba(0, 0, 0, 0.1)',
            zIndex: 101,
            overflowY: 'auto'
          }}>
          {/* Panel Header */}
          <div style={{
            padding: '16px',
            borderBottom: '1px solid #E5E7EB',
            display: 'flex',
            flexDirection: 'column',
            gap: gap4,
            flexShrink: 0
          }}>
            <div style={{
              position: 'relative',
              width: '100%'
            }}>
              <button
                onClick={handleCloseSidebar}
                style={{
                  position: 'absolute',
                  top: '-12px',
                  right: 0,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  boxShadow: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#6B7280',
                  borderRadius: 0,
                  flexShrink: 0,
                  zIndex: 1
                }}
                onFocus={(e) => e.currentTarget.style.outline = 'none'}
                onBlur={(e) => e.currentTarget.style.outline = 'none'}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
              >
                <X style={{ height: '20px', width: '20px' }} />
              </button>
              <div style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                width: '100%',
                paddingRight: '28px',
                paddingTop: '24px'
              }}>
                <h2 
                  className="template-detail-panel-title heading-m"
                  style={{
                    fontSize: '20px',
                    fontWeight: 600,
                    color: '#1F2937',
                    margin: 0,
                    fontFamily: 'Urbanist',
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    flex: 1,
                    minWidth: 0,
                    lineHeight: '24px',
                    letterSpacing: '0px',
                    maxWidth: 'calc(100% - 100px)'
                  }}
                >
                  {selectedTemplate.name}
                </h2>
              </div>
            </div>
            <p style={{
              fontSize: '11px',
              color: '#A198CE',
              fontFamily: 'Urbanist',
              margin: 0
            }}>
              {getCategoryDisplayName(selectedTemplate.category || '').toLowerCase()} template · Used {selectedTemplate.usageCount} times
            </p>
          </div>

          {/* Panel Content */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0
          }}>
            {/* Template Details Section */}
            <div style={{
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: gap12,
              flexShrink: 0
            }}>
              {/* Template Details - label outside frame, same as EMAIL CONTENT */}
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="template-label template-detail-label" style={{ marginBottom: '4px' }}>
                  TEMPLATE DETAILS
                </div>
                <div style={{
                  padding: '16px',
                  backgroundColor: '#F9FAFB',
                  borderRadius: '8px',
                  border: '0.8px solid #6B7280',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: gap12
                }}>
              {/* Category */}
              <div>
                <div style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: '#A198CE',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  marginBottom: '4px',
                  fontFamily: 'Urbanist'
                }}>
                  CATEGORY
                </div>
                <div style={{
                  display: 'inline-block',
                  padding: '4px 10px',
                  backgroundColor: '#DBEAFE',
                  color: '#193CB8',
                  border: '1px solid #DBEAFE',
                  borderRadius: '12px',
                  fontSize: '11px',
                  fontWeight: 500,
                  fontFamily: 'Urbanist',
                  lineHeight: '1.4'
                }}>
                  {getCategoryDisplayName(selectedTemplate.category || '').toLowerCase()}
                </div>
              </div>

              {/* Subject Line */}
              <div>
                <div className="template-label template-detail-label">
                  SUBJECT LINE
                </div>
                <div 
                  className="template-subject-text"
                  dangerouslySetInnerHTML={{
                    __html: highlightTemplateVariables(selectedTemplate.subject || 'No subject')
                  }}
                />
              </div>

              {/* Tags */}
              {selectedTemplate.tags && selectedTemplate.tags.length > 0 && (
                <div>
                  <div className="template-label template-detail-label">
                    TAGS
                  </div>
                  <div className="template-card-tags-container" style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: gap6
                  }}>
                    {selectedTemplate.tags.slice(0, 3).map((tag, index) => (
                      <span
                        key={index}
                        className={`template-card-tag ${index % 2 === 0 ? 'template-card-tag-primary' : 'template-card-tag-secondary'}`}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Divider Line */}
              <div style={{
                borderTop: '1px solid #E5E7EB',
                marginTop: '4px',
                marginBottom: '4px'
              }} />

              {/* Usage Count and Last Viewed - Horizontal */}
              <div style={{ display: 'flex', gap: gap16 }}>
                {/* Usage Count */}
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    color: '#A198CE',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    marginBottom: '4px',
                    fontFamily: 'Urbanist'
                  }}>
                    USAGE COUNT
                  </div>
                  <div style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    color: '#A198CE',
                    fontFamily: 'Urbanist'
                  }}>
                    {selectedTemplate.usageCount}
                  </div>
                </div>

                {/* Last Viewed */}
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    color: '#A198CE',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    marginBottom: '4px',
                    fontFamily: 'Urbanist'
                  }}>
                    LAST VIEWED
                  </div>
                  <div style={{
                    fontSize: '14px',
                    fontWeight: 600,
                    color: '#A198CE',
                    fontFamily: 'Urbanist'
                  }}>
                    {new Date().toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })}
                  </div>
                </div>
                </div>
              </div>
              </div>

              {/* Email Content - same label style as Template Details */}
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="template-label template-detail-label" style={{ marginBottom: '4px' }}>
                  EMAIL CONTENT
                </div>
                <div 
                  style={{
                    padding: '16px',
                    backgroundColor: '#F9FAFB',
                    borderRadius: '8px',
                    border: '0.8px solid #6B7280',
                    fontSize: '12px',
                    lineHeight: '1.8',
                    color: '#111827',
                    fontFamily: 'Urbanist',
                    whiteSpace: 'pre-wrap',
                    wordWrap: 'break-word'
                  }}
                  dangerouslySetInnerHTML={{
                    __html: highlightTemplateVariables(selectedTemplate.content || selectedTemplate.description || 'No content available')
                  }}
                />
              </div>
            </div>
          </div>
        </div>
        </div>
      )}

      {/* Edit Template Modal */}
      {editingTemplate && (
        <>
          {/* Overlay */}
          <div
            onClick={handleCancelEdit}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'rgba(0, 0, 0, 0.5)',
              zIndex: 10000
            }}
          />
          {/* Modal */}
          <div
            className="template-edit-modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              position: 'fixed',
              top: isMobile ? '0' : '50%',
              left: isMobile ? '0' : '50%',
              right: isMobile ? '0' : 'auto',
              bottom: isMobile ? '0' : 'auto',
              transform: isMobile ? 'none' : 'translate(-50%, -50%)',
              backgroundColor: 'white',
              borderRadius: isMobile ? '0' : '12px',
              padding: isMobile ? '16px' : '24px',
              boxShadow: isMobile ? 'none' : '0 10px 25px rgba(0, 0, 0, 0.2)',
              zIndex: 10001,
              width: isMobile ? '100%' : '600px',
              maxWidth: isMobile ? '100%' : '90vw',
              maxHeight: isMobile ? '100vh' : '80vh',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: gap12
            }}
          >
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: isMobile ? '12px' : '8px',
              flexShrink: 0
            }}>
              <h2 className="heading-l" style={{
                color: '#111827',
                margin: 0,
                fontFamily: 'Urbanist'
              }}>
                Edit Template
              </h2>
              <button
                onClick={handleCancelEdit}
                style={{
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: '4px',
                  color: '#6B7280'
                }}
              >
                <X style={{ height: '20px', width: '20px' }} />
              </button>
            </div>

            <div>
              <label style={{
                fontSize: isMobile ? '11px' : '12px',
                fontWeight: 600,
                color: '#374151',
                marginBottom: isMobile ? '4px' : '6px',
                display: 'block',
                fontFamily: 'Urbanist'
              }}>
                Template Name
              </label>
              <Input
                className="template-edit-input"
                placeholder="Template name"
                value={editingTemplate.name}
                onChange={(e) => setEditingTemplate({ ...editingTemplate, name: e.target.value })}
                style={{
                  width: '100%'
                }}
              />
            </div>

            <div>
              <label style={{
                fontSize: isMobile ? '11px' : '12px',
                fontWeight: 600,
                color: '#374151',
                marginBottom: isMobile ? '4px' : '6px',
                display: 'block',
                fontFamily: 'Urbanist'
              }}>
                Subject Line
              </label>
              <div
                ref={editSubjectRef}
                className="template-edit-subject"
                contentEditable
                data-placeholder="Subject line"
                suppressContentEditableWarning
                onInput={(e) => setEditingTemplate({ ...editingTemplate, subject: (e.currentTarget.textContent || '').trim() })}
                onBlur={(e) => {
                  const raw = (e.currentTarget.textContent || '').trim();
                  if (raw !== editingTemplate.subject) setEditingTemplate(prev => prev ? { ...prev, subject: raw } : null);
                  e.currentTarget.innerHTML = highlightTemplateVariables(raw);
                }}
                style={{
                  width: '100%',
                  minHeight: '36px',
                  padding: '8px 12px',
                  border: '1px solid #E5E7EB',
                  borderRadius: '6px',
                  fontFamily: 'Urbanist',
                  fontSize: isMobile ? '12px' : '14px',
                  outline: 'none'
                }}
              />
            </div>

            <div>
              <label style={{
                fontSize: isMobile ? '11px' : '12px',
                fontWeight: 600,
                color: '#374151',
                marginBottom: isMobile ? '4px' : '6px',
                display: 'block',
                fontFamily: 'Urbanist'
              }}>
                Email Content
              </label>
              <div
                ref={editContentRef}
                className="template-edit-content"
                contentEditable
                data-placeholder="Email content"
                suppressContentEditableWarning
                onInput={(e) => setEditingTemplate({ ...editingTemplate, content: getEditContentText(e.currentTarget) })}
                onBlur={(e) => {
                  const raw = getEditContentText(e.currentTarget);
                  if (raw !== editingTemplate.content) setEditingTemplate(prev => prev ? { ...prev, content: raw } : null);
                  e.currentTarget.innerHTML = highlightTemplateVariables(raw);
                }}
                style={{
                  width: '100%',
                  minHeight: isMobile ? '200px' : '300px',
                  padding: '8px 12px',
                  border: '1px solid #E5E7EB',
                  borderRadius: '6px',
                  fontFamily: 'Urbanist',
                  fontSize: isMobile ? '12px' : '14px',
                  lineHeight: '1.6',
                  outline: 'none',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word'
                }}
              />
            </div>

            <div style={{
              display: 'flex',
              gap: gap8,
              justifyContent: 'flex-end',
              marginTop: isMobile ? '12px' : '8px',
              flexShrink: 0
            }}>
              <button
                type="button"
                onClick={handleCancelEdit}
                className="template-edit-footer-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                className="template-edit-footer-save"
              >
                Save Changes
              </button>
            </div>
          </div>
        </>
      )}

      {/* Create New Template - Right-side sliding panel (like detail panel) */}
      {showCreateModal && (
        <div className="template-create-panel-wrapper">
          <div
            className="template-create-panel-backdrop"
            onClick={handleCancelCreate}
            aria-hidden="true"
          />
          <div
            className="template-create-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="template-create-panel-header">
              <button
                type="button"
                onClick={handleCancelCreate}
                className="template-create-close-btn"
                aria-label="Close"
              >
                <X className="template-create-close-icon" />
              </button>
            </div>
            <div className="template-create-panel-intro">
              <div className="template-create-title">
                Create New Email Template
              </div>
              <p className="template-create-subtitle">
                Create reusable email templates for your outreach campaigns
              </p>
            </div>

            {/* Form Fields */}
            <div className="template-create-form-body" style={{ 
              display: 'flex', 
              flexDirection: 'column', 
              gap: gap8,
              flex: 1,
              minHeight: 0,
              overflowY: 'auto',
              overflowX: 'hidden',
              paddingRight: '4px'
            }}>
              {/* Template Name */}
              <div style={{ width: '100%', boxSizing: 'border-box' }}>
                <label className="template-create-label">
                  Template Name<span className="template-create-label-required">*</span>
                </label>
                <Input
                  placeholder="e.g., Professional Introduction"
                  value={newTemplate.name}
                  onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })}
                  className="template-input-placeholder"
                  style={{ width: '100%', boxSizing: 'border-box' }}
                />
              </div>

              {/* Category */}
              <div style={{ width: '100%', boxSizing: 'border-box' }}>
                <label className="template-create-label">
                  Category<span className="template-create-label-required">*</span>
                </label>
                <Select 
                  value={newTemplate.category || 'professional'} 
                  onValueChange={(value) => setNewTemplate({ ...newTemplate, category: value as TemplateCard['category'] })}
                >
                  <SelectTrigger className="template-input-placeholder" style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    cursor: 'pointer'
                  }}>
                    <SelectValue placeholder="Select category" />
                  </SelectTrigger>
                  <SelectContent className="template-select-content" style={{ zIndex: 10002 }}>
                    {categories && categories.length > 0 ? (
                      categories.map((category) => (
                        <SelectItem key={category.value} value={category.value}>
                          {category.label}
                        </SelectItem>
                      ))
                    ) : (
                      <>
                        <SelectItem value="professional">Professional</SelectItem>
                        <SelectItem value="value-proposition">Value Proposition</SelectItem>
                        <SelectItem value="network-outreach">Network Outreach</SelectItem>
                      </>
                    )}
                  </SelectContent>
                </Select>
              </div>

              {/* Subject Line */}
              <div style={{ width: '100%', boxSizing: 'border-box' }}>
                <label className="template-create-label">
                  Subject Line<span className="template-create-label-required">*</span>
                </label>
                <Input
      placeholder="e.g., Introduction from your business"
                  value={newTemplate.subject}
                  onChange={(e) => setNewTemplate({ ...newTemplate, subject: e.target.value })}
                  className="template-input-placeholder"
                  style={{ width: '100%', boxSizing: 'border-box' }}
                />
                <p style={{
                  fontSize: '9px',
                  color: '#A198CE',
                  margin: '3px 0 0 0',
                  fontFamily: 'Urbanist',
                  lineHeight: '1.3'
                }}>
                  Use variables: {'{{business_name}}'}, {'{{industry}}'}, {'{{location}}'}
                </p>
              </div>

              {/* Email Content */}
              <div style={{ width: '100%', boxSizing: 'border-box' }}>
                <label className="template-create-label">
                  Email Content<span className="template-create-label-required">*</span>
                </label>
                <Textarea
                  placeholder="Write your email template here..."
                  value={newTemplate.content}
                  onChange={(e) => setNewTemplate({ ...newTemplate, content: e.target.value })}
                  className="template-input-placeholder"
                  style={{
                    width: '100%',
                    minHeight: '120px',
                    resize: 'none',
                    boxSizing: 'border-box'
                  }}
                />
                <p style={{
                  fontSize: '9px',
                  color: '#A198CE',
                  margin: '3px 0 0 0',
                  fontFamily: 'Urbanist',
                  lineHeight: '1.3'
                }}>
                  Use variables: {'{{business_name}}'}, {'{{industry}}'}, {'{{location}}'}
                </p>
              </div>

              {/* Tags */}
              <div style={{ width: '100%', boxSizing: 'border-box' }}>
                <label className="template-create-label">Tags (optional)</label>
                <div style={{
                  position: 'relative',
                  width: '100%',
                  boxSizing: 'border-box',
                  border: 'none'
                }}>
                  <Input
                    placeholder="e.g., professional, collaboration, partnership"
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyPress={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleAddTag();
                      }
                    }}
                    className="template-input-placeholder template-input-tags"
                    style={{
                      width: '100%',
                      boxSizing: 'border-box'
                    }}
                  />
                  <button
                    type="button"
                    onClick={handleAddTag}
                    style={{
                      position: 'absolute',
                      right: '4px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxSizing: 'border-box',
                      height: '24px',
                      width: '24px',
                      zIndex: 1
                    }}
                  >
                    <Plus style={{ height: 16, width: 16, color: '#9164FF' }} />
                  </button>
                </div>
                {newTemplate.tags.length > 0 && (
                  <div style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: gap4,
                    marginTop: '2px'
                  }}>
                    {newTemplate.tags.map((tag, index) => (
                      <span
                        key={index}
                        style={{
                          background: '#F3F4F6',
                          color: '#374151',
                          padding: '1px 5px',
                          borderRadius: '6px',
                          fontSize: '8px',
                          fontFamily: 'Urbanist',
                          display: 'flex',
                          flexDirection: 'row',
                          alignItems: 'center',
                          gap: gap4,
                          lineHeight: '1.2',
                          height: '18px'
                        }}
                      >
                        {tag}
                        <button
                          type="button"
                          onClick={() => handleRemoveTag(tag)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            padding: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#6B7280',
                            lineHeight: 1
                          }}
                        >
                          <X style={{ height: '7px', width: '7px' }} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <p style={{
                  fontSize: '8px',
                  color: '#A198CE',
                  margin: '2px 0 0 0',
                  fontFamily: 'Urbanist',
                  lineHeight: '1.2'
                }}>
                  Separate tags with commas to make templates easier to find
                </p>
              </div>
            </div>

            {/* Footer — secondary + primary same as Lead Log / Create Campaign */}
            <div className="template-create-footer-actions" style={{ gap: gap8 }}>
              <Button
                type="button"
                variant="outline"
                onClick={handleCancelCreate}
                className="shrink-0"
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="default"
                onClick={handleCreateTemplate}
                className="lead-log-create-campaign-btn shrink-0"
              >
                Create Template
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog - same design as Save All Leads / Confirm Removal */}
      {showDeleteConfirm && (
        <>
          <div
            onClick={cancelDelete}
            className="evecta-dialog-overlay template-confirm-delete-overlay"
          />
          <div
            onClick={(e) => e.stopPropagation()}
            className="evecta-dialog template-confirm-delete-dialog"
          >
            <div className="evecta-dialog-header template-confirm-delete-header">
              <h2 className="evecta-dialog-title template-confirm-delete-title">
                Confirm Delete
              </h2>
              <button
                type="button"
                aria-label="Close"
                onClick={cancelDelete}
                className="evecta-dialog-close template-confirm-delete-close"
              >
                <X className="evecta-dialog-close-x" aria-hidden strokeWidth={2} size={18} />
              </button>
            </div>
            <p className="evecta-dialog-description template-confirm-delete-text">
              Are you sure you want to delete this template? This action cannot be undone.
            </p>
            <div className="evecta-dialog-actions template-confirm-delete-actions">
              <button
                type="button"
                onClick={cancelDelete}
                className="evecta-dialog-btn evecta-dialog-btn--secondary template-confirm-delete-no-btn"
              >
                No
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="evecta-dialog-btn evecta-dialog-btn--destructive template-confirm-delete-yes-btn"
              >
                Yes
              </button>
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  );
}

