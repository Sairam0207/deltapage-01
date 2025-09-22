import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';
import deltaPageLogo from './assets/deltapage-logo.png';
// Use user-requested hardware image; fallback to a safe stock photo if it fails.
const HERO_IMAGE_PRIMARY = 'https://weirdwonderfulai.art/wp-content/uploads/2023/03/ai-desktop-pc-parts--980x653.jpg';
const HERO_IMAGE_FALLBACK = 'https://images.unsplash.com/photo-1518779578993-ec3579fee39f?q=80&w=1400&auto=format&fit=crop&ixlib=rb-4.0.3';

function App() {
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [products, setProducts] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [imageLoadingStates, setImageLoadingStates] = useState({});
  const [imageErrorStates, setImageErrorStates] = useState({});

  useEffect(() => {
    let isMounted = true;

    const fetchUploadedOrFeatured = async () => {
      try {
        // 1) Try to show the latest uploaded products first
        console.log("Fetching uploaded products...");
        const uploadedRes = await fetch("http://localhost:8000/uploaded-products");
        const uploadedData = await uploadedRes.json();
        const uploaded = uploadedData?.products || [];
        if (isMounted && Array.isArray(uploaded) && uploaded.length > 0) {
          setProducts(uploaded);
          setIsLoading(false);
          return; // done
        }
      } catch (e) {
        console.warn("Uploaded products not available, falling back to featured.", e);
      }

      // 2) Fallback to readonly featured tiles
      try {
        console.log("Fetching featured products from Supabase (readonly mode)...");
        const res = await fetch("http://localhost:8000/featured-products-readonly");
        const data = await res.json();
        if (isMounted) {
          setProducts(data.products || []);
        }
      } catch (err) {
        console.error("Error fetching featured products:", err);
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    fetchUploadedOrFeatured();
    return () => { isMounted = false; };
  }, []);

  const handleSendMessage = async () => {
    if (inputMessage.trim() === '') return;
    const userMessage = inputMessage.trim();
    const newMessages = [...chatMessages, { sender: 'user', text: userMessage }];
    setChatMessages(newMessages);
    setInputMessage('');
    setIsTyping(true);
    try {
      // Persist session id so history survives reloads
      let sessionId = localStorage.getItem('chatSession');
      if (!sessionId) {
        sessionId = (self.crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
        localStorage.setItem('chatSession', sessionId);
      }
      const response = await fetch('http://localhost:8000/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId, query: userMessage })
      });
      const data = await response.json();
      setChatMessages((prevMessages) => [
        ...prevMessages,
        { sender: 'bot', text: data.answer },
      ]);
    } catch (error) {
      console.error('Error sending message:', error);
      setChatMessages((prevMessages) => [
        ...prevMessages,
        { sender: 'bot', text: 'Sorry, I am unable to respond at the moment.' },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleSendMessage();
    }
  };

  const toggleChat = () => {
    setIsChatOpen(!isChatOpen);
  };

  const handleImageLoad = (productIndex) => {
    setImageLoadingStates(prev => ({
      ...prev,
      [productIndex]: false
    }));
  };

  const handleImageError = (productIndex) => {
    setImageLoadingStates(prev => ({
      ...prev,
      [productIndex]: false
    }));
    setImageErrorStates(prev => ({
      ...prev,
      [productIndex]: true
    }));
  };

  const handleImageLoadStart = (productIndex) => {
    setImageLoadingStates(prev => ({
      ...prev,
      [productIndex]: true
    }));
  };

  return (
    <div className="landing-page-container">
      <div className="main-content">
        <header className="main-header">
          <div className="header-left">
            <img src={deltaPageLogo} alt="Deltapage Logo" className="logo" />
            <span className="company-name">Deltapage.com</span>
            <nav className="header-nav">
              <a href="#categories">CATEGORIES</a>
              <a href="#sell">SELL WITH US</a>
              <a href="#deals">DEALS</a>
              <a href="#contact">CONTACT US</a>
            </nav>
          </div>
          <div className="header-right">
            <input type="text" placeholder="Search" className="search-bar" />
            <a href="#login" className="header-icon"><i className="fas fa-user"></i> Login</a>
            <a href="#cart" className="header-icon"><i className="fas fa-shopping-cart"></i> My Cart</a>
          </div>
        </header>
        <section className="hero-section">
          <div className="hero-grid">
            <div className="hero-copy">
              <span className="pill-badge">Deltapage.com • Since 1998</span>
              <h1>Build. Upgrade. Accelerate.</h1>
              <p>Curated IT hardware, trusted brands, and smart assistance for your next setup.</p>
              <div className="hero-cta">
                <button className="btn-primary">Shop Now</button>
                <button className="btn-ghost">View Deals</button>
              </div>
            </div>
            <div className="hero-device">
              <img
                src={HERO_IMAGE_PRIMARY}
                alt="Featured hardware"
                className="main-banner-image"
                onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = HERO_IMAGE_FALLBACK; }}
              />
            </div>
          </div>
        </section>
        {/* Collections section */}
        <section className="collections-section" id="collections">
          <div className="collections-header">
            <h2>Explore Collections</h2>
            <p>Shop curated picks across GPUs, CPUs, Storage, and Peripherals.</p>
          </div>
          <div className="collections-grid">
            {[
              {
                title: 'Graphics Cards',
                img: 'https://images.unsplash.com/photo-1605648916360-8e4c4d970d9b?q=80&w=1200&auto=format&fit=crop',
              },
              {
                title: 'Processors',
                img: 'https://images.unsplash.com/photo-1593642532973-d31b6557fa68?q=80&w=1200&auto=format&fit=crop',
              },
              {
                title: 'Storage & SSDs',
                img: 'https://images.unsplash.com/photo-1541807084-5c52b6b3adef?q=80&w=1200&auto=format&fit=crop',
              },
              {
                title: 'Peripherals',
                img: 'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?q=80&w=1200&auto=format&fit=crop',
              },
            ].map((c, i) => (
              <div key={i} className="collection-card">
                <img src={c.img} alt={c.title} />
                <div className="collection-overlay">
                  <h3>{c.title}</h3>
                  <button className="btn-primary small">Shop</button>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="banner-section">
          <img
            src={HERO_IMAGE_PRIMARY}
            alt="Featured banner"
            className="main-banner-image"
            onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = HERO_IMAGE_FALLBACK; }}
          />
        </section>
        <section className="products-section">
          <h2>Featured Products</h2>
          <div className="product-list">
            {isLoading ? (
              <div className="loading-container">
                <div className="loading-spinner"></div>
        <p>Loading featured products...</p>
        <small>Fetching from Supabase (no Firecrawl calls)</small>
              </div>
            ) : products.length > 0 ? (
              products.map((p, i) => (
                <div key={i} className="product-item">
                  <div className="product-image-container">
                    {imageLoadingStates[i] && (
                      <div className="image-loading">
                        <div className="loading-spinner"></div>
                        <span>Loading...</span>
                      </div>
                    )}
                    {imageErrorStates[i] ? (
                      <div className="image-placeholder">
                        <i className="fas fa-image"></i>
                        <span>Image not available</span>
                      </div>
                    ) : (
                      <img 
                        src={p.image_url} 
                        alt={p.product_name || p.name || 'Product'}
                        onLoadStart={() => handleImageLoadStart(i)}
                        onLoad={() => handleImageLoad(i)}
                        onError={() => handleImageError(i)}
                        style={{ display: imageLoadingStates[i] ? 'none' : 'block' }}
                      />
                    )}
                  </div>
                  <h3>{p.product_name || p.name || 'Product'}</h3>
                  {p.description && <p className="product-description">{p.description}</p>}
                  {p.price && <p className="product-price">₹{p.price}</p>}
                </div>
              ))
            ) : (
              <p>No products found.</p>
            )}
          </div>
        </section>
        <footer className="main-footer">
          <div className="footer-column">
            <h3>Home</h3>
            <a href="#">About Us</a>
            <a href="#">Products</a>
            <a href="#">Terms & Conditions</a>
            <a href="#">Privacy Policy</a>
            <a href="#">Contact Us</a>
          </div>
          <div className="footer-column">
            <h3>What We Do</h3>
            <p>We sell IT Hardware, PC Building Solutions, Servers, & Network Racks. Also we do PC Spares, Upgrades & Service for your PCs & Laptops.</p>
          </div>
          <div className="footer-column">
            <h3>Connect with us</h3>
            <p><i className="fas fa-map-marker-alt"></i> Contact Us: G-1, First floor, 24th Main, HSR Layout, Sector-2, Bangalore 560102.</p>
            <p><i className="fas fa-envelope"></i> <a href="mailto:contactus@deltapage.com">contactus@deltapage.com</a></p>
            <p><i className="fas fa-phone"></i> +91 9986423110</p>
            <div className="social-links">
              <a href="#"><i className="fab fa-facebook-f"></i></a>
              <a href="#"><i className="fab fa-twitter"></i></a>
              <a href="#"><i className="fab fa-linkedin-in"></i></a>
            </div>
          </div>
          <div className="copyright">
            <p>Copyright © Delta Holgenosis</p>
          </div>
        </footer>
      </div>
      {!isChatOpen && (
        <button className="open-query-button" onClick={toggleChat}>
          Open Query Chatbot
        </button>
      )}
      {isChatOpen && (
        <div className="chat-sidebar">
          <div className="chat-header">
            <h3>Chat with Us</h3>
            <p>Ask about products, orders, and more!</p>
            <button className="close-chat-button" onClick={toggleChat}>&times;</button>
          </div>
          <div className="chat-messages">
            {chatMessages.map((msg, index) => (
              <div key={index} className={`message ${msg.sender}`}>
                <div className="message-bubble">
                  {msg.sender === 'user' ? msg.text : <ReactMarkdown>{msg.text}</ReactMarkdown>}
                </div>
              </div>
            ))}
            {isTyping && (
              <div className="message bot typing-indicator">
                <div className="typing-dots"><span></span><span></span><span></span></div>
              </div>
            )}
          </div>
          <div className="chat-input-area">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your message..."
              className="chat-input"
              disabled={isTyping}
            />
            <button onClick={handleSendMessage} className="send-button" disabled={isTyping}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.28 12.399a.75.75 0 0 1 .472-.676L20.274 5.31a.75.75 0 0 1 .951.849l-1.554 8.761a.75.75 0 0 1-1.37.078l-3.515-6.195-2.035 2.035a.75.75 0 0 1-1.06 0L5.31 9.774l-6.195 3.515a.75.75 0 0 1-.078 1.37l8.761 1.554a.75.75 0 0 1 .849-.951L12.399 21.72a.75.75 0 0 1-.676.472L2.28 12.399Z" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
