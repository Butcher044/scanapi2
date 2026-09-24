import { useEffect, useRef } from 'react'

/** Ref that is false once the component unmounts: async mutations check it before setState. */
export function useMounted() {
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  return mounted
}
