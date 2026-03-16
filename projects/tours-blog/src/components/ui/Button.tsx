import React from 'react';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  children: React.ReactNode;
  className?: string;
};

const Button: React.FC<ButtonProps> = ({ children, className, ...props }) => (
  <button className={`px-4 py-2 rounded bg-blue-600 text-white ${className || ''}`} {...props}>
    {children}
  </button>
);

export default Button;