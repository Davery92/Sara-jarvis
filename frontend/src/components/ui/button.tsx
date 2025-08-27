import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost' | 'secondary';
  size?: 'sm' | 'default' | 'lg';
}

export function Button({ 
  className = '', 
  variant = 'default', 
  size = 'default',
  children, 
  disabled = false,
  ...props 
}: ButtonProps) {
  const baseClasses = 'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none ring-offset-background';
  
  const variantClasses = {
    default: 'bg-teal-600 text-white hover:bg-teal-700',
    outline: 'border border-gray-600 bg-transparent text-gray-300 hover:bg-gray-800 hover:text-white',
    ghost: 'hover:bg-gray-800 hover:text-white text-gray-300',
    secondary: 'bg-gray-700 text-gray-200 hover:bg-gray-600'
  };
  
  const sizeClasses = {
    sm: 'h-9 px-3',
    default: 'h-10 px-4 py-2',
    lg: 'h-11 px-8'
  };
  
  const classes = `${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`;
  
  return (
    <button 
      className={classes}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}