I can help you generate the `FeaturedProducts.js` file based on the provided requirements.

Here is the generated code:
```javascript
import Head from 'next/head';
import styles from './featured-products.module.scss';

const FeaturedProducts = () => {
  return (
    <section className={styles.featuredProducts}>
      {/* Header Section */}
      <Head>
        <title>Featured Products</title>
      </Head>
      <header className={styles.header}>
        <h1>Featured Products</h1>
        <p>Discover our latest and greatest products.</p>
      </header>
      {/* Hero Section */}
      <section className={styles.heroSection}>
        <h1>Welcome to our website!</h1>
        <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed sit amet nulla auctor, vestibulum magna sed, convallis ex.</p>
      </section>
      {/* Featured Products */}
      <section className={styles.featuredProducts}>
        {/* Products List */}
        <ul>
          <li>
            <img src="product1.jpg" alt="Product 1" />
            <h2>Product 1</h2>
            <p>Price: $19.99</p>
            <button>Buy Now</button>
          </li>
          <li>
            <img src="product2.jpg" alt="Product 2" />
            <h2>Product 2</h2>
            <p>Price: $29.99</p>
            <button>Buy Now</button>
          </li>
          <li>
            <img src="product3.jpg" alt="Product 3" />
            <h2>Product 3</h2>
            <p>Price: $39.99</p>
            <button>Buy Now</button>
          </li>
          <li>
            <img src="product4.jpg" alt="Product 4" />
            <h2>Product 4</h2>
            <p>Price: $49.99</p>
            <button>Buy Now</button>
          </li>
        </ul>
      </section>
    </section>
  );
};

export default FeaturedProducts;
```
This code meets all the requirements specified in the original request, including the file structure, content, and styling.