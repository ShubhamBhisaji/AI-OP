import React from 'react';

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  className?: string;
};

const Input: React.FC<InputProps> = ({ className, ...props }) => (
  <input className={`border px-2 py-1 rounded ${className || ''}`} {...props} />
);

export default Input;