from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import plotly.express as px
from wordcloud import WordCloud
from datetime import datetime, timedelta
from collections import Counter
from nltk.corpus import stopwords
from textblob import TextBlob
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired
import os
import re
from xhtml2pdf import pisa
import io
import nltk
import json

# Ensure NLTK stopwords are downloaded
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

# Load data
file_path = "reduced_reviews_per_product.xlsx"  # Update with your file path
data = pd.read_excel(file_path)
data['Date'] = pd.to_datetime(data['Date'], errors='coerce')

# Ensure the static folder exists for saving images
if not os.path.exists('static'):
    os.makedirs('static')

# Feedback Form
class FeedbackForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired()])
    message = TextAreaField('Message', validators=[DataRequired()])
    submit = SubmitField('Submit')

# Helper Functions
def keyword_analysis(comments):
    stop_words = set(stopwords.words('english'))
    word_count = Counter()

    for comment in comments:
        words = comment.lower().split()
        filtered_words = [word for word in words if word.isalpha() and word not in stop_words]
        word_count.update(filtered_words)

    return word_count

def generate_wordcloud(word_count, product_name):
    if not word_count:
        return None

    sanitized_name = re.sub(r'[\\/:*?"<>|]', '_', product_name)
    if not os.path.exists('static'):
        os.makedirs('static')

    wordcloud = WordCloud(width=800, height=400, background_color="white").generate_from_frequencies(word_count)
    image_path = f"static/{sanitized_name}_wordcloud.png"

    try:
        wordcloud.to_file(image_path)
        return image_path
    except Exception as e:
        print(f"Error saving word cloud: {e}")
        return None

def generate_report(avg_rating):
    if avg_rating < 1:
        return "This product has received extremely poor feedback overall. Buyers have expressed significant dissatisfaction."
    elif avg_rating < 2.5:
        return "This product has below-average reviews, with several customers highlighting issues."
    elif avg_rating < 3.5:
        return "This product has mixed reviews, with customers expressing both positive and negative experiences."
    elif avg_rating < 4.5:
        return "This product is well-received, with mostly positive feedback and a few concerns."
    else:
        return "This product has excellent reviews, with customers overwhelmingly satisfied."

def filter_by_timeline(data, timeline):
    if timeline == 'all':
        return data
    cutoff_date = datetime.now() - timedelta(days=30 * int(timeline))
    return data[data['Date'] >= cutoff_date]

def generate_timeline_reports(data, product, timeline):
    filtered_data = filter_by_timeline(data, timeline)
    product_data = filtered_data[filtered_data['Product Name'] == product]

    if product_data.empty:
        return f"No data available for the product '{product}' in the selected timeline."
    
    avg_rating = product_data['Rating'].mean()
    comments = product_data['Comment'].dropna().tolist()
    word_count = keyword_analysis(comments)
    top_keywords = word_count.most_common(5)

    # Sentiment Analysis
    sentiments = [TextBlob(comment).sentiment.polarity for comment in comments]
    sentiment_distribution = {
        'Positive': len([s for s in sentiments if s > 0]),
        'Neutral': len([s for s in sentiments if s == 0]),
        'Negative': len([s for s in sentiments if s < 0])
    }

    report = {
        'Product': product,
        'Average Rating': avg_rating,
        'Top Keywords': top_keywords,
        'Word Count': word_count,
        'Report': generate_report(avg_rating),
        'Sentiment Distribution': sentiment_distribution
    }
    return report

# Routes
@app.route('/')
def home():
    products = data['Product Name'].unique()
    return render_template('index.html', products=products)

@app.route('/report', methods=['POST'])
def report():
    product = request.form['product']
    timeline = request.form['timeline']
    
    report = generate_timeline_reports(data, product, timeline)
    if isinstance(report, str):
        return render_template('report.html', message=report)
    
    wordcloud_path = generate_wordcloud(report['Word Count'], product)

    # Convert sentiment_distribution to JSON
    sentiment_json = json.dumps(report['Sentiment Distribution'])

    return render_template('report.html', 
                           product=report['Product'], 
                           avg_rating=round(report['Average Rating'], 2), 
                           top_keywords=report['Top Keywords'], 
                           report_text=report['Report'], 
                           wordcloud_path=wordcloud_path,
                           sentiment_distribution=sentiment_json,
                           timeline=timeline)

@app.route('/compare', methods=['GET', 'POST'])
def compare():
    if request.method == 'POST':
        selected_products = request.form.getlist('products')
        timeline = request.form['timeline']
        
        filtered_data = filter_by_timeline(data, timeline)
        fig = px.line(title='Product Rating Comparison')

        for product in selected_products:
            product_data = filtered_data[filtered_data['Product Name'] == product]
            product_data = product_data.sort_values(by='Date')
            fig.add_scatter(x=product_data['Date'], y=product_data['Rating'], mode='lines+markers', name=product)

        fig.update_layout(
            xaxis_title='Date',
            yaxis_title='Rating',
            legend_title='Products',
            hovermode='x unified',
            width=1400,
            height=500
        )

        plot_html = fig.to_html(full_html=False)
        return render_template('compare.html', plot_html=plot_html)

    products = data['Product Name'].unique()
    return render_template('compare.html', products=products)

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    form = FeedbackForm()
    if form.validate_on_submit():
        # Save feedback to a file or database
        with open('feedback.txt', 'a') as f:
            f.write(f"Name: {form.name.data}, Email: {form.email.data}, Message: {form.message.data}\n")
        return "Thank you for your feedback!"
    return render_template('feedback.html', form=form)

@app.route('/export-pdf', methods=['POST'])
def export_pdf():
    product = request.form['product']
    timeline = request.form['timeline']
    
    report = generate_timeline_reports(data, product, timeline)
    if isinstance(report, str):
        return report

    html = render_template('pdf_template.html', 
                           product=report['Product'], 
                           avg_rating=round(report['Average Rating'], 2), 
                           top_keywords=report['Top Keywords'], 
                           report_text=report['Report'])

    pdf = io.BytesIO()
    pisa.CreatePDF(html, dest=pdf)
    pdf.seek(0)

    return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name=f"{report['Product']}_report.pdf")

if __name__ == '__main__':
    app.run(debug=True)