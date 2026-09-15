import { useEffect, useRef, useState } from 'react';

export default function useContainerWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(300);
  useEffect(() => {
    const element = ref.current;
    const measure = () => {
      const next = element?.getBoundingClientRect().width;
      if (next > 0) setWidth(next);
    };
    measure();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  return [ref, width];
}
