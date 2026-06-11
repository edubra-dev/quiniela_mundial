import React from 'react'
import ScoringRules from '../components/ScoringRules'

export default function Home() {
  return (
    <div>
      <main className="min-h-screen flex items-start justify-center py-12 px-4">
        <section className="w-full max-w-4xl">
          <ScoringRules />
        </section>
      </main>
    </div>
  )
}
