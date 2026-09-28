// A job's own page: come back to a running or failed analysis after navigating away.
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import JobProgress from '../../components/JobProgress'

export default function JobPage() {
  const { id } = useParams()
  const [output, setOutput] = useState(null)
  return (
    <div className="mx-auto max-w-md p-6">
      <JobProgress jobId={Number(id)} onSucceeded={setOutput} />
      {output?.report_id && (
        <Link to={`/areas/reports/${output.report_id}`} className="mt-4 inline-block text-brand underline">
          Open report #{output.report_id}
        </Link>
      )}
    </div>
  )
}
