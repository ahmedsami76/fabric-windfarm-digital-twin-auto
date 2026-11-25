/**
 * What a function of the app returned, as the shape the page expects.
 *
 * The functions return JSON text. The Rayfin client parses JSON text by itself before it hands the
 * answer over (`FunctionClient.invoke` of `@microsoft/rayfin-functions`: "Auto-parse JSON-encoded
 * output strings"), so the page normally receives the object, not the text. Both are accepted: the
 * object as it is, text parsed here. The first deployment showed only "did not return JSON", because
 * the page parsed a second time what was already an object.
 *
 * A function that could not do its work returns `{ "error": … }` with the reason (`Failure` of the
 * contract). That becomes an error here, with the reason as its message.
 */
export function fromFunction<T>(value: unknown, name: string): T {
  if (typeof value === 'string') {
    const text = value;
    try {
      value = JSON.parse(text) as unknown;
    } catch {
      throw new Error(`The function ${name} did not return JSON. It returned: ${text.slice(0, 200)}`);
    }
  }
  if (value === null || value === undefined || typeof value !== 'object') {
    throw new Error(`The function ${name} returned ${value === undefined ? 'nothing' : String(value)}.`);
  }
  const failure = (value as { error?: unknown }).error;
  if (typeof failure === 'string' && !Array.isArray(value) && Object.keys(value).length === 1) {
    throw new Error(failure);
  }
  return value as T;
}
