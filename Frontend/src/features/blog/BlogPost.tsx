import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { MoveLeft, Search, RefreshCw, TrendingUp, Mail, Target, Lightbulb, Users, Zap, BarChart3, CheckCircle, LucideIcon } from 'lucide-react';
import { Button } from '../../features/dashboard/components/ui/button';
import { blogData } from '../../shared/data/blogData';
import { HomePageHeader, HomePageFooter } from '../homepage/HomePage';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import '../homepage/HomePage.css';
import './BlogPage.css';
import './BlogPost.css';

const BlogPost = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const handleGetStarted = () => {
    navigate('/auth');
  };

  const handleContactClick = () => {
    // Navigate to contact or open contact modal
    window.location.href = '#contact';
  };
  const blog = useMemo(() => blogData.find((b: any) => b.id === id) ?? null, [id]);
  const [activeSection, setActiveSection] = useState('');
  const [tocItems, setTocItems] = useState<any[]>([]);
  const [isSaved, setIsSaved] = useState(false);
  const [viewCount, setViewCount] = useState<number>(0);
  const sectionRefs = useRef({});

  useEffect(() => {
    if (blog) generateToc(blog);
  }, [blog]);

  // Initialize saved state once blog data is available
  useEffect(() => {
    if (!blog) return;
    try {
      const saved = JSON.parse(localStorage.getItem('savedArticles') || '[]');
      setIsSaved(saved.includes(blog.id));
    } catch (e) {
      // ignore malformed storage
      setIsSaved(false);
    }
  }, [blog]);

  // Increment and read view count from localStorage so counts match the list page
  useEffect(() => {
    if (!blog) return;
    try {
      const key = 'blogViews';
      const raw = localStorage.getItem(key);
      const stored = raw ? JSON.parse(raw) : {};
      const current = Number(stored[blog.id] || 0) + 1; // count a view
      stored[blog.id] = current;
      localStorage.setItem(key, JSON.stringify(stored));
      setViewCount(current);
    } catch (e) {
      // storage unavailable
      setViewCount((v) => (v || 0) + 1);
    }
  }, [blog]);

  const generateToc = (blogData: any) => {
    const toc = [];
    
    // Add introduction
    if (blogData.content.introduction) {
      toc.push({
        id: 'introduction',
        title: 'Introduction',
        level: 1
      });
    }

    // Add sections and subsections
    if (blogData.content.sections) {
      blogData.content.sections.forEach((section, sectionIndex) => {
        toc.push({
          id: `section-${sectionIndex}`,
          title: section.title,
          level: 1
        });

        if (section.subsections) {
          section.subsections.forEach((subsection, subIndex) => {
            toc.push({
              id: `section-${sectionIndex}-sub-${subIndex}`,
              title: subsection.title,
              level: 2
            });
          });
        }
      });
    }

    // Add conclusion
    if (blogData.content.conclusion) {
      toc.push({
        id: 'conclusion',
        title: 'Conclusion',
        level: 1
      });
    }

    setTocItems(toc);
  };

  // Intersection Observer for active section highlighting
  useEffect(() => {
    if (tocItems.length === 0) return;

    const observerOptions = {
      root: null,
      rootMargin: '-20% 0px -70% 0px',
      threshold: 0
    };

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          setActiveSection(entry.target.id);
        }
      });
    }, observerOptions);

    // Observe all sections
    tocItems.forEach((item) => {
      const element = document.getElementById(item.id);
      if (element) {
        observer.observe(element);
      }
    });

    return () => {
      observer.disconnect();
    };
  }, [tocItems]);

  const scrollToSection = (sectionId: any) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ 
        behavior: 'smooth',
        block: 'start'
      });
    }
  };

  const handleBackToBlog = () => {
    navigate('/blog');
  };

  const handleShare = async () => {
    if (!blog) return;
    const shareData = {
      title: blog.title,
      text: blog.excerpt || blog.title,
      url: window.location.href
    } as any;

    try {
      if (navigator.share) {
        await (navigator as any).share(shareData);
        return;
      }
    } catch (err) {
      // fall through to clipboard
    }

    try {
      await navigator.clipboard.writeText(window.location.href);
      alert('Link copied to clipboard');
    } catch (err) {
      alert('Unable to share. Please copy the URL from the address bar.');
    }
  };

  const handleToggleSave = () => {
    if (!blog) return;
    try {
      const key = 'savedArticles';
      const raw = localStorage.getItem(key);
      const list = raw ? JSON.parse(raw) : [];
      const idx = list.indexOf(blog.id);
      if (idx >= 0) {
        list.splice(idx, 1);
        setIsSaved(false);
      } else {
        list.push(blog.id);
        setIsSaved(true);
      }
      localStorage.setItem(key, JSON.stringify(list));
      
      // Dispatch custom event to notify BlogPage about the update
      window.dispatchEvent(new Event('savedArticlesUpdated'));
    } catch (e) {
      // storage might be unavailable
      alert('Unable to save locally in this browser mode.');
    }
  };

  const blogHeaderSection = (
    <section className="blog-header-section">
      <div className="blog-content-inner">
        <div className="text-center">
          <p className="homepage-why-choose-badge text-sm font-medium mb-2">Blog</p>
          <h1 className="heading-xl text-gray-900 mb-1">
            Latest from Evecta
          </h1>
          <p className="blog-header-subtitle text-lg max-w-2xl mx-auto mb-6">
            <span className="blog-header-subtitle-desktop">
              A chronicle of our latest milestones, breakthroughs,<br />
              and industry-leading news.
            </span>
            <span className="blog-header-subtitle-mobile">
              A chronicle of our latest milestones,
              <br />
              breakthroughs, and industry-leading
              <br />
              news.
            </span>
          </p>
          <div className="max-w-2xl mx-auto blog-search-row">
            <input
              type="text"
              placeholder="Search here..."
              className="w-full blog-search-input"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const q = (e.target as HTMLInputElement).value.trim();
                  navigate(q ? `/blog?search=${encodeURIComponent(q)}` : '/blog');
                }
              }}
            />
          </div>
        </div>
      </div>
    </section>
  );

  if (!blog) {
    return (
      <div className="homepage blog-post-page min-h-screen homepage-gradient-bg theme-dark">
        <PageSeo
          title="Blog post not found"
          description="This Evecta blog post could not be found."
          path={`/blog/${id ?? ''}`}
          noindex
        />
        <HomePageHeader isDark />
        <div className="blog-page-content">
        {blogHeaderSection}
        <div className="blog-post-page-inner">
          <div className="blog-post-layout">
            <div className="blog-post-main">
              <div className="error-container">
                <h2 className="heading-l">Blog post not found</h2>
                <p>The blog post you're looking for doesn't exist.</p>
              </div>
            </div>
          </div>
        </div>
        </div>
        <HomePageFooter />
      </div>
    );
  }

  return (
    <div className="homepage blog-post-page min-h-screen homepage-gradient-bg theme-dark">
      <PageSeo
        title={blog.title}
        description={blog.excerpt}
        path={`/blog/${blog.id}`}
        image={blog.featuredImage}
        type="article"
      />
      <HomePageHeader isDark />
      <div className="blog-page-content">
      {blogHeaderSection}
      <div className="blog-post-page">
      {/* Content area without TOC */}
      <div className="blog-post-layout no-toc">
        {/* Main Content */}
        <div className="blog-post-main">
          <article className="blog-post-content">
            {/* Our Story label above title with arrow on left – arrow links back to blog */}
            <div className="blog-post-our-story-wrap">
              <Link to="/blog" className="blog-post-our-story-arrow-link" aria-label="Back to blog">
                <MoveLeft className="blog-post-our-story-arrow" aria-hidden />
              </Link>
              <p className="blog-post-our-story-badge">Our Story</p>
            </div>

            {/* Meta + Title */}
            <header className="blog-post-header-content">
              <h1 className="blog-post-title heading-xl">{blog.title}</h1>
            </header>

            {/* Intro - split by double newlines for paragraphs */}
            {blog.content.introduction && (
              <div id="introduction" className="blog-post-introduction">
                {(typeof blog.content.introduction === 'string'
                  ? blog.content.introduction.split(/\n\s*\n/).filter(Boolean)
                  : [blog.content.introduction]
                ).map((para, i) => (
                  <p key={i}>{para.trim()}</p>
                ))}
              </div>
            )}

            {/* Flat article: no section/subsection headings, only paragraphs; optional points cards block */}
            {(blog as any).displayAsFlatArticle && blog.content.sections && (
              <div className="blog-post-flat-body">
                {blog.content.sections.map((section: any, sectionIndex: number) => (
                  <React.Fragment key={sectionIndex}>
                    {section.renderAsCardsInFlat && section.subsections && section.subsections.length >= 2 ? (
                      <div className="blog-post-section blog-points-cards-wrap">
                        <div className="blog-points-cards">
                          {section.subsections.map((sub: any, subIndex: number) => {
                            const iconNames = (section.subsectionIcons || []) as string[];
                            const defaultIcons: LucideIcon[] = [Target, Lightbulb, TrendingUp, Mail, Search, RefreshCw, Zap, Users, BarChart3, CheckCircle];
                            const iconMap: Record<string, LucideIcon> = { Search, RefreshCw, TrendingUp, Mail, Target, Lightbulb, Users, Zap, BarChart3, CheckCircle };
                            const IconComponent = iconNames[subIndex] ? (iconMap[iconNames[subIndex]] || defaultIcons[subIndex % defaultIcons.length]) : defaultIcons[subIndex % defaultIcons.length];
                            return (
                              <div key={subIndex} className="blog-point-card">
                                <IconComponent className="blog-point-icon" aria-hidden />
                                <h3 className="blog-point-title">{sub.title}</h3>
                                <p className="blog-point-description">{sub.content}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : (
                      section.subsections && section.subsections.map((sub: any, subIndex: number) => (
                        <div key={subIndex} className="blog-post-flat-paragraphs">
                          {(typeof sub.content === 'string'
                            ? sub.content.split(/\n\s*\n/).filter(Boolean)
                            : [sub.content]
                          ).map((para: string, i: number) => (
                            <p key={i}>{para.trim()}</p>
                          ))}
                        </div>
                      ))
                    )}
                    {(blog.content as any).midContentImage && (blog.content as any).midImageAfterSectionIndex === sectionIndex && (
                      <div className="blog-post-mid-image">
                        <img src={(blog.content as any).midContentImage} alt="" />
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>
            )}

            {/* Sections with headings (when not flat) */}
            {!(blog as any).displayAsFlatArticle && blog.content.sections && blog.content.sections.map((section, sectionIndex) => {
              const subsections = section.subsections || [];
              const useCards = subsections.length >= 2;
              const iconNames = ((section as any).subsectionIcons || []) as string[];
              const defaultIcons: LucideIcon[] = [Target, Lightbulb, TrendingUp, Mail, Search, RefreshCw, Zap, Users, BarChart3, CheckCircle];
              const iconMap: Record<string, LucideIcon> = { Search, RefreshCw, TrendingUp, Mail, Target, Lightbulb, Users, Zap, BarChart3, CheckCircle };
              return (
              <React.Fragment key={sectionIndex}>
                <div id={`section-${sectionIndex}`} className="blog-post-section">
                  <h2 className="section-title heading-l">{section.title}</h2>
                  {useCards ? (
                    <div className="blog-points-cards">
                      {subsections.map((subsection: any, subIndex: number) => {
                        const IconComponent = iconNames[subIndex] ? (iconMap[iconNames[subIndex]] || defaultIcons[subIndex % defaultIcons.length]) : defaultIcons[subIndex % defaultIcons.length];
                        return (
                          <div key={subIndex} id={`section-${sectionIndex}-sub-${subIndex}`} className="blog-point-card">
                            <IconComponent className="blog-point-icon" aria-hidden />
                            <h3 className="blog-point-title">{subsection.title}</h3>
                            <p className="blog-point-description">{subsection.content}</p>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    section.subsections && section.subsections.map((subsection: any, subIndex: number) => (
                      <div key={subIndex} id={`section-${sectionIndex}-sub-${subIndex}`} className="blog-post-subsection">
                        <h3 className="subsection-title">{subsection.title}</h3>
                        <div className="subsection-content">
                          <p>{subsection.content}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
                {(blog.content as any).midContentImage && (blog.content as any).midImageAfterSectionIndex === sectionIndex && (
                  <div className="blog-post-mid-image">
                    <img src={(blog.content as any).midContentImage} alt="" />
                  </div>
                )}
              </React.Fragment>
            );
            })}

            {/* Conclusion */}
            {(blog.content as { conclusion?: string }).conclusion && (
              <div id="conclusion" className="blog-post-conclusion">
                <h2>Conclusion</h2>
                <p>{(blog.content as { conclusion?: string }).conclusion}</p>
              </div>
            )}

            {/* Footer actions - buttons removed */}
            <div className="article-actions">
            </div>
          </article>
        </div>
      </div>
      </div>
      </div>
      <HomePageFooter />
    </div>
  );
};

export default BlogPost;