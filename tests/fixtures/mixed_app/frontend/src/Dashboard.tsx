import React from 'react';
import { createPayment } from './api';

export const Dashboard = () => {
  const submitPayment = () => createPayment(100);
  return <button onClick={submitPayment}>Pay</button>;
};
