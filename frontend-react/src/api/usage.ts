/**
 * Domain wrapper — usage and quota.
 *
 * `GET /usage` reports per-service Groq quota plus local-backend availability.
 * It had no wrapper in the React client at all until the sidebar needed the
 * footer line; the endpoint existed and the Streamlit app read it.
 */
import { get } from './client'
import type { UsageOut } from './types'

export const usage = {
  get: (): Promise<UsageOut> => get('/usage'),
}
