import React, { useState } from 'react';
import './App.css';

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [products, setProducts] = useState([]); // Store products from backend

  const handleFileChange = (event) => {
    setSelectedFile(event.target.files[0]);
    setMessage('');
    setProducts([]); // Reset previous products
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setMessage('Please select a file first!');
      return;
    }

    setIsLoading(true);
    setMessage('Uploading and processing document...');

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch("http://127.0.0.1:8000/upload", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        setMessage(data.message || "Upload successful!");
        
        // After successful upload, fetch featured products (this will trigger Firecrawl calls)
        setMessage('Upload successful! Now fetching featured product images...');
        const featuredResponse = await fetch("http://127.0.0.1:8000/featured-products");
        const featuredData = await featuredResponse.json();
        
        if (featuredResponse.ok) {
          setProducts(featuredData.products || []);
          setMessage(`Upload successful! Fetched ${featuredData.products?.length || 0} featured products with images.`);
        } else {
          setMessage('Upload successful, but failed to fetch featured products.');
        }
      } else {
        setMessage(data.error || 'Upload failed.');
      }
    } catch (error) {
      console.error('Error uploading document:', error);
      setMessage('Error uploading document. Check the backend server.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="admin-container">
      <div className="admin-card">
        <h1>Document Uploader</h1>
        <p className="subtitle">Power the chatbot with your knowledge base.</p>
        
        <div className="file-input-group">
          <label htmlFor="file-upload" className="custom-file-upload">
            {selectedFile ? selectedFile.name : 'Choose a TXT file'}
          </label>
          <input
            id="file-upload"
            type="file"
            accept=".txt"
            onChange={handleFileChange}
          />
        </div>

        <button 
          onClick={handleUpload} 
          disabled={!selectedFile || isLoading}
          className="upload-button"
        >
          {isLoading ? 'Processing...' : 'Upload Document'}
        </button>
        
        {message && (
          <p className={`status-message ${isLoading ? 'loading' : ''}`}>
            {message}
          </p>
        )}

        {/* Product preview section */}
        {products.length > 0 && (
          <div className="products-grid">
            {products.map((p, index) => (
              <div key={index} className="product-card">
                <img
                  src={p.image_url}
                  alt={p.product_name}
                  className="product-image"
                />
                <p className="product-name">{p.product_name}</p>
                {p.description && <p className="product-description">{p.description}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
