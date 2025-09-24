import { redirect } from 'next/navigation'

export default function Home() {
  // Server-side redirect to the login page
  redirect('/login')
  return null
}
