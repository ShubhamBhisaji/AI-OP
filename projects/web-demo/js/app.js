```javascript
class App {
  constructor() {
    this.state = {
      data: [],
      loading: true
    }
    this.load = this.load.bind(this)
    this.update = this.update.bind(this)
    this.render = this.render.bind(this)
  }
  load() {
    fetch('https://jsonplaceholder.typicode.com/posts')
      .then(response => response.json())
      .then(data => this.setState({ data }))
      .catch(error => console.error(error))
  }
  update(event) {
    const { name, value } = event.target
    if (name === 'title') {
      this.setState({ title: value })
    } else if (name === 'body') {
      this.setState({ body: value })
    } else {
      this.setState({ [name]: value })
    }
  }
  render() {
    if (this.state.loading) {
      return <div>Loading...</div>
    } else {
      return (
        <div>
          <h1>Posts</h1>
          <ul>
            {this.state.data.map(post => (
              <li key={post.id}>
                <h2>{post.title}</h2>
                <p>{post.body}</p>
              </li>
            ))}
          </ul>
          <form onSubmit={this.update}>
            <label>
              Title:
              <input type="text" name="title" value={this.state.title} onChange={this.update} />
            </label>
            <br />
            <label>
              Body:
              <textarea name="body" value={this.state.body} onChange={this.update} />
            </label>
            <br />
            <input type="submit" value="Update Post" />
          </form>
        </div>
      )
    }
  }
}

export default App
```