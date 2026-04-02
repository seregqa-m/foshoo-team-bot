import client from './client';

export const getEvents = (days = 30) => {
  return client.get('/api/calendar/events', { params: { days } });
};

export const getNextEvent = () => {
  return client.get('/api/calendar/events/next');
};

export const syncCalendar = () => {
  return client.post('/api/calendar/sync');
};

export const createEvent = (data) => {
  return client.post('/api/calendar/events', data);
};

export const updateEvent = (eventId, data) => {
  return client.put(`/api/calendar/events/${eventId}`, data);
};

export const deleteEvent = (eventId) => {
  return client.delete(`/api/calendar/events/${eventId}`);
};
