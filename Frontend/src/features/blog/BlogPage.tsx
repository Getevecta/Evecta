import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '../../features/dashboard/components/ui/button';
import { blogData } from '../../shared/data/blogData';
import { HomePageHeader, HomePageFooter } from '../homepage/HomePage';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';
import '../homepage/HomePage.css';
import './BlogPage.css';

function blogMatchesQuery(
  blog: (typeof blogData)[number],
  raw: string
): boolean {
  const q = raw.trim().toLowerCase();
  if (!q) return true;
  const parts = q.split(/\s+/).filter(Boolean);
  const hay = [blog.title, blog.excerpt, blog.category, blog.author]
    .join(' ')
    .toLowerCase();
  return parts.every((p) => hay.includes(p));
}

const BlogPage = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const handleGetStarted = () => {
    navigate('/auth');
  };

  const handleContactClick = () => {
    // Navigate to contact or open contact modal
    window.location.href = '#contact';
  };
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [visibleBlogs, setVisibleBlogs] = useState(8); // Show 8 blogs initially
  const [isLoading, setIsLoading] = useState(false);
  const [likedBlogs, setLikedBlogs] = useState(new Set()); // Track liked blog IDs
  const [blogLikes, setBlogLikes] = useState({}); // Track like counts for each blog
  const [blogViews, setBlogViews] = useState({}); // Track view counts for each blog
  const [savedArticles, setSavedArticles] = useState(new Set()); // Track saved article IDs
  const [showTOC, setShowTOC] = useState(false); // deprecated, overlay removed
  const [activeArticleId, setActiveArticleId] = useState('');
  const contentScrollRef = useRef<HTMLDivElement | null>(null);
  const tocListRef = useRef<HTMLUListElement | null>(null);

  const categories = ['All', 'Strategy', 'Analytics', 'Technology', 'Marketing'];

  const [searchText, setSearchText] = useState(() => searchParams.get('search') ?? '');

  useEffect(() => {
    setSearchText(searchParams.get('search') ?? '');
  }, [searchParams]);

  const commitSearchToUrl = () => {
    const t = searchText.trim();
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (t) next.set('search', t);
        else next.delete('search');
        return next;
      },
      { replace: true }
    );
  };

  const filteredBlogs = (
    selectedCategory === 'All'
      ? blogData
      : blogData.filter((blog) => blog.category === selectedCategory)
  ).filter((blog) => blogMatchesQuery(blog, searchText));

  const displayedBlogs = filteredBlogs.slice(0, visibleBlogs);
  const hasMoreBlogs = visibleBlogs < filteredBlogs.length;

  // Initialize like counts (mock) and persistent view counts
  React.useEffect(() => {
    const initialLikes = {} as any;
    blogData.forEach(blog => {
      initialLikes[blog.id] = Math.floor(Math.random() * 50) + 10; // Random like count between 10-60
    });
    setBlogLikes(initialLikes);

    try {
      const key = 'blogViews';
      const raw = localStorage.getItem(key);
      const stored = raw ? JSON.parse(raw) : {};
      // Seed any missing ids once
      blogData.forEach(b => {
        if (stored[b.id] == null) {
          stored[b.id] = Math.floor(Math.random() * 8000) + 120;
        }
      });
      localStorage.setItem(key, JSON.stringify(stored));
      setBlogViews(stored);
    } catch (e) {
      // Fallback to zeros when storage is unavailable
      const zeros = {} as any;
      blogData.forEach(b => { zeros[b.id] = 0; });
      setBlogViews(zeros);
    }

    // Load saved articles from localStorage
    const loadSavedArticles = () => {
      try {
        const savedKey = 'savedArticles';
        const savedRaw = localStorage.getItem(savedKey);
        const savedList = savedRaw ? JSON.parse(savedRaw) : [];
        setSavedArticles(new Set(savedList));
      } catch (e) {
        // If storage unavailable, keep empty set
        setSavedArticles(new Set());
      }
    };

    loadSavedArticles();

    // Listen for storage changes (when articles are saved/unsaved from other tabs or pages)
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'savedArticles') {
        loadSavedArticles();
      }
    };

    window.addEventListener('storage', handleStorageChange);

    // Also listen for custom events from the same tab (when saving from BlogPost page)
    const handleCustomStorage = () => {
      loadSavedArticles();
    };

    window.addEventListener('savedArticlesUpdated', handleCustomStorage);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('savedArticlesUpdated', handleCustomStorage);
    };
  }, []);

  const handleBlogClick = (blogId: any) => {
    const blog = blogData.find(b => b.id === blogId);
    if (blog) {
      // Navigate to blog post in the same page
      const blogUrl = `/blog/${blogId}`;
      navigate(blogUrl);
    }
  };


  const handleLoadMore = async () => {
    setIsLoading(true);
    // Simulate loading delay
    await new Promise(resolve => setTimeout(resolve, 1000));
    setVisibleBlogs(prev => prev + 8);
    setIsLoading(false);
  };

  const handleLike = (blogId: any, e: any) => {
    e.stopPropagation(); // Prevent triggering blog click
    
    const isLiked = likedBlogs.has(blogId);
    
    setLikedBlogs(prev => {
      const newLikedBlogs = new Set(prev);
      if (isLiked) {
        newLikedBlogs.delete(blogId);
      } else {
        newLikedBlogs.add(blogId);
      }
      return newLikedBlogs;
    });

    setBlogLikes(prev => ({
      ...prev,
      [blogId]: prev[blogId] + (isLiked ? -1 : 1)
    }));
  };

  // Observe article cards and highlight the active one in left TOC
  useEffect(() => {
    if (!displayedBlogs || displayedBlogs.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const id = (entry.target as HTMLElement).id.replace('blog-', '');
            setActiveArticleId(id);
          }
        });
      },
      { root: contentScrollRef.current, rootMargin: '-20% 0px -70% 0px', threshold: 0 }
    );

    displayedBlogs.forEach((b) => {
      const el = document.getElementById(`blog-${b.id}`);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [displayedBlogs]);

  // Auto-scroll TOC list to keep active in view within its own area
  useEffect(() => {
    if (!activeArticleId || !tocListRef.current) return;
    const el = tocListRef.current.querySelector(`#toc-item-${activeArticleId}`) as HTMLElement | null;
    if (el) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [activeArticleId]);

  useEffect(() => {
    setVisibleBlogs(8);
  }, [searchText, selectedCategory]);

  return (
    <div className="homepage blog-page min-h-screen homepage-gradient-bg theme-dark">
      <PageSeo
        title="Blog"
        description="Latest from Evecta — product updates, growth strategy, and B2B lead generation insights."
        path="/blog"
      />
      <HomePageHeader isDark />
      <div className="blog-page-content">
      <div className="blog-page-layout">
        <div className="blog-page-main">
      {/* Blog Header Section */}
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
            {/* Search Bar */}
            <form
              className="max-w-2xl mx-auto blog-search-row"
              role="search"
              onSubmit={(e) => {
                e.preventDefault();
                commitSearchToUrl();
              }}
            >
              <input
                type="search"
                name="blog-search"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setSearchText('');
                    setSearchParams((prev) => {
                      const next = new URLSearchParams(prev);
                      next.delete('search');
                      return next;
                    }, { replace: true });
                  }
                }}
                placeholder="Search here..."
                className="w-full blog-search-input"
                autoComplete="off"
                aria-label="Search blog posts"
              />
            </form>
          </div>
        </div>
      </section>

      {/* Main Content Area */}
      <section className="blog-main-content pb-12">
        <div className="blog-content-inner">
          <div>
            <div className="blog-card-list">
              {displayedBlogs.length === 0 ? (
                <div className="blog-card-empty text-center py-12">
                  <h3>No blog articles found</h3>
                  <p>
                    {searchText.trim()
                      ? 'Try different keywords or clear the search box.'
                      : 'Please check back later for new content.'}
                  </p>
                </div>
              ) : (
                displayedBlogs.map((blog: any) => (
                  <article
                    key={blog.id}
                    className="blog-content-card"
                    onClick={() => handleBlogClick(blog.id)}
                  >
                    <div className="blog-card-image-wrap">
                      <img
                        src={blog.featuredImage}
                        alt={blog.title}
                        className="blog-card-image"
                      />
                    </div>
                    <div className="blog-card-body">
                      <span className="blog-card-category">{blog.category}</span>
                      <h3 className="blog-card-title">{blog.title}</h3>
                      <p className="blog-card-excerpt">{blog.excerpt}</p>
                      <span className="blog-card-read-more">Read More</span>
                    </div>
                  </article>
                ))
              )}
            </div>

            {hasMoreBlogs && false && (
              <div className="mt-8 text-center">
              </div>
            )}
          </div>
        </div>
      </section>
        </div>
      </div>
      </div>
      <HomePageFooter />
    </div>
  );
};

export default BlogPage;



