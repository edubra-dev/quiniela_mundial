import React from 'react'

export default function ScoringRules() {
  return (
    <section className="w-full bg-transparent text-slate-900 dark:text-slate-100 py-12">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="prose prose-slate dark:prose-invert lg:prose-lg">
          <h1>🏆 ¿Cómo sumar puntos en nuestra Quiniela?</h1>
          <p>
            ¡Nuestro sistema de puntuación premia tu precisión! No solo juegas a
            ganar o empatar, cada gol exacto que pronostiques te acerca a la
            cima de la tabla. Aquí no hay reglas confusas: los puntos se van
            sumando según tus aciertos en cada partido. ¡Mira cómo funciona!
          </p>

          <h2>📊 Reglas de Puntuación</h2>
          <p>Por cada partido que juegues, puedes sumar puntos de la siguiente manera:</p>
          <ul>
            <li><strong>Puntos Base (+3 pts):</strong> Si aciertas qué equipo gana el partido o si logras predecir que terminará en empate.</li>
            <li><strong>Bono Local (+1 pt):</strong> Si aciertas exactamente la cantidad de goles que mete el equipo LOCAL.</li>
            <li><strong>Bono Visitante (+1 pt):</strong> Si aciertas exactamente la cantidad de goles que mete el equipo VISITANTE.</li>
          </ul>

          <blockquote className="border-l-4 border-sky-400 pl-4 italic bg-slate-50 dark:bg-slate-800 rounded-md py-3">
            Puntaje Máximo por Partido: ¡5 puntos si logras el marcador exacto!
          </blockquote>

          <h2>💡 Ejemplos Prácticos</h2>
          <p>(Resultado Real de ejemplo: 2 – 1)</p>
        </div>

        <div className="mt-6">
          <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
            <table className="w-full table-auto text-left">
              <thead className="bg-slate-50 dark:bg-slate-800">
                <tr>
                  <th className="px-4 py-3 text-sm font-medium">Tu Predicción</th>
                  <th className="px-4 py-3 text-sm font-medium">¿Qué acertaste?</th>
                  <th className="px-4 py-3 text-sm font-medium">Tus Puntos</th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-slate-900">
                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">2 – 1</td>
                  <td className="px-4 py-4 text-sm">¡Marcador Exacto! (Ganador + Goles Local + Goles Visitante)</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gradient-to-r from-yellow-400 to-yellow-500 text-slate-900 font-bold">
                      5 pts <span className="text-sm">🔥</span>
                    </span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">2 – 0</td>
                  <td className="px-4 py-4 text-sm">Acertaste el Ganador y los goles del Local.</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-sky-100 dark:bg-sky-900 text-sky-800 dark:text-sky-200 font-semibold">4 pts</span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">3 – 1</td>
                  <td className="px-4 py-4 text-sm">Acertaste el Ganador y los goles del Visitante.</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-sky-100 dark:bg-sky-900 text-sky-800 dark:text-sky-200 font-semibold">4 pts</span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">3 – 0</td>
                  <td className="px-4 py-4 text-sm">Solo acertaste el Ganador (fallaste ambos goles).</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-emerald-100 dark:bg-emerald-900 text-emerald-800 dark:text-emerald-200 font-semibold">3 pts</span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">2 – 2</td>
                  <td className="px-4 py-4 text-sm">Fallaste el Ganador, pero le atinaste a los goles del Local.</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-800 dark:text-indigo-200 font-semibold">1 pt</span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">0 – 1</td>
                  <td className="px-4 py-4 text-sm">Fallaste el Ganador, pero le atinaste a los goles del Visitante.</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-800 dark:text-indigo-200 font-semibold">1 pt</span>
                  </td>
                </tr>

                <tr className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <td className="px-4 py-4 text-sm font-semibold">0 – 3</td>
                  <td className="px-4 py-4 text-sm">No acertaste ninguna de las opciones.</td>
                  <td className="px-4 py-4 text-sm">
                    <span className="inline-flex items-center px-3 py-1 rounded-full bg-rose-100 dark:bg-rose-900 text-rose-800 dark:text-rose-200 font-semibold">0 pts</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="mt-6 prose prose-slate dark:prose-invert lg:prose-lg">
            <p>⚡ ¡Prepara tus pronósticos!</p>
            <p>Analiza bien a cada equipo. Recuerda que incluso si un partido no sale como esperabas, ¡un solo gol exacto te puede mantener en la jugada!</p>
          </div>

          <div className="mt-6 flex flex-col sm:flex-row gap-3 items-center">
            <a href="/app" className="inline-flex items-center justify-center px-5 py-3 rounded-md bg-sky-600 hover:bg-sky-700 text-white font-semibold shadow-md">Ir a mi Quiniela</a>
            <a href="/admin-panel" className="inline-flex items-center justify-center px-5 py-3 rounded-md border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 font-medium">Ver Reglas en Admin</a>
          </div>
        </div>
      </div>
    </section>
  )
}
