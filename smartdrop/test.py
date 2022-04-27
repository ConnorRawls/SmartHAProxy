import pickle
from sklearn.ensemble import GradientBoostingRegressor

x = [0.000868, 1.1938488888888888e-09, 0.05, 0.1]

model = pickle.load(open('GBDT.sav', 'rb'))

yhat = model.predict([x])

print(f"\nResults: {yhat}")