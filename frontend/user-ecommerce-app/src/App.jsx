import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

// Import assets from your assets folder.
import deltaPageLogo from './assets/deltapage-logo.png'; 
import mainBannerImage from './assets/main-banner.png'; 

function App() {
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [products, setProducts] = useState([]); // NEW state for products

  // Fetch products dynamically from backend
  useEffect(() => {
    const fetchProducts = async () => {
      try {
        const res = await fetch("http://localhost:8000/products");
        const data = await res.json();
        setProducts(data.products || []);
      } catch (err) {
        console.error("Error fetching products:", err);
      }
    };
    fetchProducts();
  }, []);

  const handleSendMessage = async () => {
    if (inputMessage.trim() === '') return;

    const userMessage = inputMessage.trim();
    const newMessages = [...chatMessages, { sender: 'user', text: userMessage }];
    setChatMessages(newMessages);
    setInputMessage('');
    setIsTyping(true);

    try {
      const chatUrl = `http://localhost:8000/chat?query=${encodeURIComponent(userMessage)}`;
      const response = await fetch(chatUrl);
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
          <div className="hero-content">
            <div className="hero-brand">
              <img src={deltaPageLogo} alt="Deltapage Logo" className="hero-logo" />
              <p>India's First Online IT Store... Since 1998!</p>
            </div>
            <h2>Best Offers!</h2>
            <p>100% Genuine Products</p>
            <button className="shop-now-button">SHOP NOW</button>
          </div>
        </section>

        <section className="banner-section">
          <img src={mainBannerImage} alt="Time to Upgrade Banner" className="main-banner-image" />
        </section>

        {/* DYNAMIC PRODUCTS SECTION */}
        <section className="products-section">
          <h2>Our Top Products</h2>
          <div className="product-list">
            {products.length > 0 ? (
              products.map((p) => (
                <div key={p.id} className="product-item">
                  <img src={p.image_url} alt={p.name} />
                  <h3>{p.name}</h3>
                  {p.price !== undefined && <p>₹{p.price}</p>}
                </div>
              ))
            ) : (
              <p>Loading products...</p>
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
            <p>We are a team of gaming building, PC’s Servers, & Laptops... on for your choice.</p>
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
      
      {/* Chatbot */}
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
                  {msg.sender === 'user' ? (
                    msg.text
                  ) : (
                    <ReactMarkdown>{msg.text}</ReactMarkdown>
                  )}
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
