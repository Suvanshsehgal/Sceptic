import React, { useState, useEffect } from 'react'

function App() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetch('/api/health')
      .then(res => res.json())
      .then(data => setHealth(data))
      .catch(err => setHealth({ error: err.toString() }))
  }, [])

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold underline mb-4">
        Sceptic - Phase 1
      </h1>
      <div className="p-4 bg-gray-100 rounded-lg">
        <h2 className="text-xl font-semibold mb-2">Backend Connection Status:</h2>
        {health ? (
          <pre className="bg-gray-800 text-green-400 p-4 rounded overflow-auto">
            {JSON.stringify(health, null, 2)}
          </pre>
        ) : (
          <p>Connecting to backend...</p>
        )}
      </div>
    </div>
  )
}

export default App