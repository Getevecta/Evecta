
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
/* After App.css so dialog close sizing wins over global button/icon rules */
import './shared/styles/EvectaDialog.css';
import './shared/styles/EvectaButtonHover.css';

const root = ReactDOM.createRoot(document.getElementById('root')!);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);


