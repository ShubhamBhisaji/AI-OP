```
import { useState, useEffect } from 'react';

const ComponentA = () => {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const intervalId = setInterval(() => {
      setCount(count + 1);
    }, 1000);

    return () => clearInterval(intervalId);
  }, []);

  return (
    <div>
      <p>Component A</p>
      <p>Count: {count}</p>
    </div>
  );
};

const ComponentB = () => {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const intervalId = setInterval(() => {
      setCount(count + 1);
    }, 1000);

    return () => clearInterval(intervalId);
  }, []);

  return (
    <div>
      <p>Component B</p>
      <p>Count: {count}</p>
    </div>
  );
};

export default {
  name: 'ComponentA',
  functional: true,
  props: {
    name: String,
  },
  slots: {
    name: {
      functional: true,
      props: {
        name: String,
      },
      default: () => <ComponentA />,
    },
  },
};
```