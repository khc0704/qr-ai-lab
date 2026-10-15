"""Data exploration jobs (kind = analysis): pure functions that turn a file into a JSON report.

* ``tabular.profile``      – column stats, correlations, collinearity (VIF), relevance to the target, recommendations
* ``image.quality_report`` – IQA metrics per image, drift of each metric across groups (folders), embeddings and
                             group similarity, outliers, recommendations
"""
