import React from 'react';

type CardProps = {
  children: React.ReactNode;
  className?: string;
};

const Card: React.FC<CardProps> = ({ children, className }) => (
  <div className={`bg-white rounded shadow ${className || ''}`}>
    {children}
  </div>
);

export default Card;