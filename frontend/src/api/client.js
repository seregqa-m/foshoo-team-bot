import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

const client = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default client;
