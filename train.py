import numpy as np
import tensorflow as tf
import pandas as pd
import optparse
from tensorflow.python.client import device_lib
from tensorflow import keras as kr
from tensorflow.keras import losses
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

##from utils import plotHist

import numba
import json

#from models import *
from qDenseCNN import qDenseCNN
from denseCNN import denseCNN

#for earth movers distance calculation
import ot

@numba.jit
def normalize(data,rescaleInputToMax=False):
    norm =[]
    for i in range(len(data)):
        if rescaleInputToMax:
            norm.append( data[i].max() )
            data[i] = 1.*data[i]/data[i].max()
        else:
            norm.append( data[i].sum() )
            data[i] = 1.*data[i]/data[i].sum()
    return data,np.array(norm)

def plotHist(vals,name,odir='.',xtitle="",ytitle="",nbins=40,
             stats=True, logy=False, leg=None):
    plt.figure(figsize=(6,4))
    if leg:
        plt.hist(vals,nbins,label=leg)
    else:
        plt.hist(vals,nbins)
    ax = plt.axes()
    plt.text(0.1, 0.9, name,transform=ax.transAxes)
    if stats:
        mu = np.mean(vals)
        std = np.std(vals)
        plt.text(0.1, 0.8, r'$\mu=%.3f,\ \sigma=%.3f$'%(mu,std),transform=ax.transAxes)
    plt.xlabel(xtitle)
    plt.ylabel(ytitle if ytitle else 'Entries')
    if logy: plt.yscale('log')
    plt.savefig(odir+"/"+name+".png")
    plt.close()
    return

def split(shaped_data, validation_frac=0.2):
    N = round(len(shaped_data)*validation_frac)
    
    #randomly select 25% entries
    val_index = np.random.choice(shaped_data.shape[0], N, replace=False)
    #select the indices of the other 75%
    full_index = np.array(range(0,len(shaped_data)))
    train_index = np.logical_not(np.in1d(full_index,val_index))
  
    val_input = shaped_data[val_index]
    train_input = shaped_data[train_index]

    print('training shape',train_input.shape)
    print('validation shape',val_input.shape)

    return val_input,train_input,val_index

def train(autoencoder,encoder,train_input,val_input,name,n_epochs=100):

    es = kr.callbacks.EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=3)
    history = autoencoder.fit(train_input,train_input,
                              epochs=n_epochs,
                              batch_size=500,
                              shuffle=True,
                              validation_data=(val_input,val_input),
                              callbacks=[es]
    )

    plt.plot(history.history['loss'])
    plt.plot(history.history['val_loss'])
    plt.title('Model loss %s'%name)
    plt.ylabel('Loss')
    plt.xlabel('Epoch')
    plt.legend(['Train', 'Test'], loc='upper right')
    plt.savefig("history_%s.png"%name)
    plt.close()

    save_models(autoencoder,name)

    return history

def save_models(autoencoder, name):
    json_string = autoencoder.to_json()
    with open('./%s.json'%name,'w') as f:
        f.write(json_string)
        encoder = autoencoder.get_layer("encoder")
        json_string = encoder.to_json()
        with open('./%s.json'%("encoder_"+name),'w') as f:
            f.write(json_string)
            decoder = autoencoder.get_layer("decoder")
            json_string = decoder.to_json()
            with open('./%s.json'%("decoder_"+name),'w') as f:
                f.write(json_string)
                autoencoder.save_weights('%s.hdf5'%name)
                encoder.save_weights('%s.hdf5'%("encoder_"+name))
                decoder.save_weights('%s.hdf5'%("decoder_"+name))
                return

### cross correlation of input/output 
def cross_corr(x,y):
    cov = np.cov(x.flatten(),y.flatten())
    std = np.sqrt(np.diag(cov))
    stdsqr = np.multiply.outer(std, std)
    corr = np.divide(cov, stdsqr, out=np.zeros_like(cov), where=(stdsqr!=0))
    return corr[0,1]

def ssd(x,y):
    if (np.sum(x)==0 or np.sum(y)==0): return 1.
    ssd=np.sum(((x-y)**2).flatten())
    ssd = ssd/(np.sum(x**2)*np.sum(y**2))**0.5
    return ssd

# calculate "earth mover's distance"
# (cost, in distance, to move earth from one config to another)
hexCoords = np.array([ 
    [0.0, 0.0], [0.0, -2.4168015], [0.0, -4.833603], [0.0, -7.2504044], 
    [2.09301, -1.2083969], [2.09301, -3.6251984], [2.09301, -6.042], [2.09301, -8.458794], 
    [4.18602, -2.4168015], [4.18602, -4.833603], [4.18602, -7.2504044], [4.18602, -9.667198], 
    [6.27903, -3.6251984], [6.27903, -6.042], [6.27903, -8.458794], [6.27903, -10.875603], 
    [-8.37204, -10.271393], [-6.27903, -9.063004], [-4.18602, -7.854599], [-2.0930138, -6.6461945], 
    [-8.37204, -7.854599], [-6.27903, -6.6461945], [-4.18602, -5.4377975], [-2.0930138, -4.229393], 
    [-8.37204, -5.4377975], [-6.27903, -4.229393], [-4.18602, -3.020996], [-2.0930138, -1.8125992], 
    [-8.37204, -3.020996], [-6.27903, -1.8125992], [-4.18602, -0.6042023], [-2.0930138, 0.6042023], 
    [4.7092705, -12.386101], [2.6162605, -11.177696], [0.5232506, -9.969299], [-1.5697594, -8.760895], 
    [2.6162605, -13.594498], [0.5232506, -12.386101], [-1.5697594, -11.177696], [-3.6627693, -9.969299], 
    [0.5232506, -14.802895], [-1.5697594, -13.594498], [-3.6627693, -12.386101], [-5.7557793, -11.177696], 
    [-1.5697594, -16.0113], [-3.6627693, -14.802895], [-5.7557793, -13.594498], [-7.848793, -12.386101]])
hexMetric = ot.dist(hexCoords, hexCoords, 'euclidean')
MAXDIST = 16.08806614
def emd(_x, _y, threshold=-1):
    if (np.sum(_x)==0 or np.sum(_y)==0): return MAXDIST
    x = np.array(_x, dtype=np.float64)
    y = np.array(_y, dtype=np.float64)
    x = (1./x.sum() if x.sum() else 1.)*x.flatten()
    y = (1./y.sum() if y.sum() else 1.)*y.flatten()

    if threshold > 0:
        # only keep entries above 2%, e.g.
        x = np.where(x>threshold,x,0)
        y = np.where(y>threshold,y,0)
        x = 1.*x/x.sum()
        y = 1.*y/y.sum()

    return ot.emd2(x, y, hexMetric)

def d_weighted_mean(x, y):
    if (np.sum(x)==0 or np.sum(y)==0): return MAXDIST/2.
    x = (1./x.sum() if x.sum() else 1.)*x.flatten()
    y = (1./y.sum() if y.sum() else 1.)*y.flatten()
    dx = hexCoords[:,0].dot(x-y)
    dy = hexCoords[:,1].dot(x-y)
    return np.sqrt(dx*dx+dy*dy)

def make_supercells(inQ, shareQ=False):
    outQ = inQ.copy()
    inshape = inQ[0].shape
    mask = np.array([
        [ 0,  1,  4,  5], #indices for 1 supercell
        [ 2,  3,  6,  7],
        [ 8,  9, 12, 13],
        [10, 11, 14, 15],
        [16, 17, 20, 21],
        [18, 19, 22, 23],
        [24, 25, 28, 29],
        [26, 27, 30, 31],
        [32, 33, 36, 37],
        [34, 35, 38, 39],
        [40, 41, 44, 45],
        [43, 43, 46, 47]])
    for i in range(len(inQ)):
        inFlat = inQ[i].flatten()
        outFlat = outQ[i].flatten()
        for sc in mask:
            # set max cell to sum
            if shareQ:
                mysum = np.sum( inFlat[sc] )
                outFlat[sc]=mysum/4.
            else:
                ii = np.argmax( inFlat[sc] )
                mysum = np.sum( inFlat[sc] )
                outFlat[sc]=0
                outFlat[sc[ii]]=mysum
        outQ[i] = outFlat.reshape(inshape)
    return outQ

def threshold(_x, norm, cut):
    x = _x.copy()
    # reshape to allow broadcasting to all cells
    norm_shape = norm.reshape((norm.shape[0],)+(1,)*(x.ndim-1))
    x = np.where(x*norm_shape>=cut,x,0)
    return x

def visDisplays(index,input_Q,decoded_Q,encoded_Q=np.array([]),name='model_X'):
    Nevents = len(index)
        
    inputImg    = input_Q[index]
    outputImg   = decoded_Q[index]

    nrows = 3 if len(encoded_Q) else 2
    fig, axs = plt.subplots(nrows, Nevents, figsize=(16, 10))
    
    for i in range(0,Nevents):
        if i==0:
            axs[0,i].set(xlabel='',ylabel='cell_y',title='Input_%i'%i)
        else:
            axs[0,i].set(xlabel='',title='Input_%i'%i)        
            c1=axs[0,i].imshow(inputImg[i])
            
    for i in range(0,Nevents):
        if i==0:
            axs[1,i].set(xlabel='cell_x',ylabel='cell_y',title='CNN Ouput_%i'%i)        
        else:
            axs[1,i].set(xlabel='cell_x',title='CNN Ouput_%i'%i)
            c1=axs[1,i].imshow(outputImg[i])

    if len(encoded_Q):
        encodedImg  = encoded_Q[index]
        for i in range(0,Nevents):
            if i==0:
                axs[2,i].set(xlabel='latent dim',ylabel='depth',title='Encoded_%i'%i)
            else:
                axs[2,i].set(xlabel='latent dim',title='Encoded_%i'%i)
                c1=axs[2,i].imshow(encodedImg[i])
                plt.colorbar(c1,ax=axs[2,i])
            
    plt.tight_layout()
    plt.savefig("%s_examples.png"%name)
    plt.close()

def visMetric(input_Q,decoded_Q,metric,name,odir,skipPlot=False):

    plotHist(vals,name,options.odir,xtitle=longMetric[mname])

    plt.figure(figsize=(6,4))
    plt.hist([input_Q.flatten(),decoded_Q.flatten()],20,label=['input','output'])
    plt.yscale('log')
    plt.legend(loc='upper right')
    plt.xlabel('Charge fraction')
    plt.savefig("hist_Qfr_%s.png"%name)
    plt.close()

    input_Q_abs   = np.array([input_Q[i] * maxQ[i] for i in range(0,len(input_Q))])
    decoded_Q_abs = np.array([decoded_Q[i]*maxQ[i] for i in range(0,len(decoded_Q))])

    nonzeroQs = np.count_nonzero(input_Q_abs.reshape(len(input_Q_abs),48),axis=1)
    occbins = [0,5,10,20,48]
    fig, axes = plt.subplots(1,len(occbins)-1, figsize=(16, 4))
    for i,ax in enumerate(axes):
        #print(cross_corr_arr[selection])
        selection=np.logical_and(nonzeroQs<occbins[i+1],nonzeroQs>occbins[i])
        label = '%i<occ<%i'%(occbins[i],occbins[i+1])
        mu = np.mean(cross_corr_arr[selection])
        std = np.std(cross_corr_arr[selection])
        plt.text(0.1, 0.8, r'$\mu=%.3f,\ \sigma=%.3f$'%(mu,std),transform=ax.transAxes)
        ax.hist(cross_corr_arr[selection],40)
        ax.set(xlabel='corr',title=label)
        plt.tight_layout()
        #plt.show()
        plt.savefig('corr_vs_occ_%s.png'%name)
        plt.close()

    return cross_corr_arr,ssd_arr,emd_arr

def GetBitsString(In, Accum, Weight, Encoded, Dense=False, Conv=False):
    s=""
    s += "Input{}b{}i".format(In['total'],In['integer'])
    s += "_Accum{}b{}i".format(Accum['total'],Accum['integer'])
    if Dense:
        s += "_Dense{}b{}i".format(Dense['total'], Dense['integer'])
        if Conv:
            s += "_Conv{}b{}i".format(Conv['total'], Conv['integer'])
        else:
            s += "_Conv{}b{}i".format(Weight['total'], Weight['integer'])
    elif Conv:
        s += "_Dense{}b{}i".format(Weight['total'], Weight['integer'])
        s += "_Conv{}b{}i".format(Conv['total'], Conv['integer'])
    else:
        s += "_Weight{}b{}i".format(Weight['total'],Weight['integer'])
    s += "_Encod{}b{}i".format(Encoded['total'], Encoded['integer'])
    return s

def trainCNN(options, args, pam_updates=None):
    # List devices:
    print(device_lib.list_local_devices())
    print("Num GPUs Available: ", len(tf.config.experimental.list_physical_devices('GPU')))
    print("Is GPU available? ", tf.test.is_gpu_available())

    # default precisions for quantized training
    nBits_input  = {'total': 32, 'integer': 4}
    nBits_accum  = {'total': 32, 'integer': 4}
    nBits_weight = {'total': 32, 'integer': 4}
    nBits_encod  = {'total': 32, 'integer': 4}
    # model-dependent -- use common weights unless overridden
    conv_qbits = nBits_weight
    dense_qbits = nBits_weight
    
  
    # from tensorflow.keras import backend
    # backend.set_image_data_format('channels_first')
    if os.path.isdir(options.inputFile):
        df_arr = []
        for infile in os.listdir(options.inputFile):
            infile = os.path.join(options.inputFile,infile)
            df_arr.append(pd.read_csv(infile, dtype=np.float64, header=0, usecols=[*range(1, 49)]))
        data = pd.concat(df_arr)
        data = data.loc[(data.sum(axis=1) != 0)] #drop rows where occupancy = 0
        print(data.shape)
        data.describe()
    else:
        data = pd.read_csv(options.inputFile,dtype=np.float64)
    #data = pd.read_csv(options.inputFile,dtype=np.float64)  ## big  300k file
    normdata,maxdata = normalize(data.values.copy(),rescaleInputToMax=options.rescaleInputToMax)

    arrange8x8 = np.array([
        28,29,30,31,0,4,8,12,
        24,25,26,27,1,5,9,13,
        20,21,22,23,2,6,10,14,
        16,17,18,19,3,7,11,15,
        47,43,39,35,35,34,33,32,
        46,42,38,34,39,38,37,36,
        45,41,37,33,43,42,41,40,
        44,40,36,32,47,46,45,44])
    
    arrMask  =  np.array([
        1,1,1,1,1,1,1,1,
        1,1,1,1,1,1,1,1,
        1,1,1,1,1,1,1,1,
        1,1,1,1,1,1,1,1,
        1,1,1,1,1,1,1,1,
        1,1,1,0,0,1,1,1,
        1,1,0,0,0,0,0,1,
        1,0,0,0,0,0,0,1,])
    
    arrange443 = np.array([0,16, 32,
                           1,17, 33,
                           2,18, 34,
                           3,19, 35,
                           4,20, 36,
                           5,21, 37,
                           6,22, 38,
                           7,23, 39,
                           8,24, 40,
                           9,25, 41,
                           10,26, 42,
                           11,27, 43,
                           12,28, 44,
                           13,29, 45,
                           14,30, 46,
                           15,31, 47])
    
    models = [
        #{'name': '4x4_norm_d10', 'ws': '',
        # 'pams': {'shape': (4, 4, 3),
        #          'channels_first': False,
        #          'arrange': arrange443,
        #          'encoded_dim': 10,
        #          'loss': 'weightedMSE'}},
        {'name': '4x4_norm_v7', 'ws': '',
         'pams': {'shape': (4, 4, 3),
                  'channels_first': False,
                  'arrange': arrange443,
                  #'loss': 'weightedMSE',
                  'loss': 'sink',
                  'CNN_layer_nodes': [4, 4, 4],
                  'CNN_kernel_size': [5, 5, 3],
                  'CNN_pool': [False, False, False], }},

    ]

    #{'name':'denseCNN',  'ws':'denseCNN.hdf5', 'pams':{'shape':(1,8,8) } },
        #{'name':'denseCNN_2',  'ws':'denseCNN_2.hdf5',
        #  'pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask  } },

    #{'name':'8x8_nomask','ws':'','pams':{'shape':(8,8,1) ,'arrange': arrange8x8  }},
        #{'name':'nfil4','ws':'','pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,  'CNN_layer_nodes':[4]}},
        #{'name':'nfils_842','ws':'nfils_842.hdf5','pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,
        #        'CNN_layer_nodes':[8,4,2],
        #        'CNN_kernel_size':[3,3,3],
        #        'CNN_pool':[False,False,False],
        #}} ,
    #{'name':'nfils_842_pool2','ws':'','pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,
        #        'CNN_layer_nodes':[8,4,2],
        #        'CNN_kernel_size':[3,3,3],
        #        'CNN_pool':[False,True,False],
        #}} ,
    #{'name':'8x8_dim10','ws':'','vis_shape':(8,8),'pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,  'encoded_dim':10}},
        #{'name':'8x8_dim8','ws':'','pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,  'encoded_dim':8}},
        #{'name':'8x8_dim4','ws':'','pams':{'shape':(8,8,1) ,'arrange': arrange8x8,'arrMask':arrMask,  'encoded_dim':4}},
        #{'name':'12x4_norm','ws':'','vis_shape':(12,4),'pams':{'shape':(12,4,1),
        #        'CNN_layer_nodes':[8,4,4,2],
        #        'CNN_kernel_size':[3,3,3,3],
        #        'CNN_pool':[False,False,False,False],
        #}},

    #{'name':'4x4_norm'    ,'ws':'4x4_norm.hdf5'    ,'pams':{'shape':(3,4,4) ,'channels_first':True }},
        #{'name':'4x4_norm_d10','ws':'4x4_norm_d10.hdf5','pams':{'shape':(3,4,4) ,'channels_first':False ,
        #                                                       'encoded_dim':10, 'qbits':qBitStr}},
        #{'name':'4x4_norm_d8' ,'ws':'4x4_norm_d8.hdf5' ,'pams':{'shape':(3,4,4) ,'channels_first':True ,'encoded_dim':8}},

    #{'name':'4x4_v1',  'ws':'','vis_shape':(4,12),'pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,8],
        #     'CNN_kernel_size':[3,3],
        #     'CNN_pool':[False,False],
        #}},
    #{'name':'4x4_v2',  'ws':'','vis_shape':(4,12),'pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,8],
        #     'CNN_kernel_size':[3,3],
        #     'CNN_pool':[False,False],
        #     'Dense_layer_nodes':[16],
        #}},
    #{'name':'4x4_v3' ,'ws':'4x4_v3.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True ,'CNN_kernel_size':[2]}},
        #{'name':'4x4_norm_v4','ws':'4x4_norm_v4.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[4,4,4],
        #     'CNN_kernel_size':[3,3,3],
        #     'CNN_pool':[False,False,False],
        #}},
    #{'name':'4x4_norm_v5','ws':'4x4_norm_v5.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True ,
        #     'CNN_layer_nodes':[8,4,2],
        #     'CNN_kernel_size':[3,3,3],
        #     'CNN_pool':[False,False,False],
        #}},
    #{'name':'4x4_norm_v6','ws':'4x4_norm_v6.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True ,
        #     'CNN_layer_nodes':[8,4,2],
        #     'CNN_kernel_size':[5,5,3],
        #     'CNN_pool':[False,False,False],
        #}},
    #{'name':'4x4_norm_v7','ws':'4x4_norm_v7.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[4,4,4],
        #     'CNN_kernel_size':[5,5,3],
        #     'CNN_pool':[False,False,False],
        #}},
    #{'name':'4x4_norm_v8','ws':'','pams':{'shape':(4,4,3) ,'channels_first':False,'arrange':arrange443,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #}},
    #{'name':'4x4_norm_v8_clone10','ws':'','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #     'n_copy':10,'occ_low':20,'occ_hi':48,
        #}},
    #{'name':'4x4_norm_v8_wmse','ws':'4x4_norm_v8_wmse.hdf5','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #     'loss':'weightedMSE'
        #}},
    #{'name':'4x4_norm_v8_KL','ws':'','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #     'loss':'kullback_leibler_divergence'
        #}},
    #{'name':'4x4_norm_v8_skimOcc','ws':'','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #     'skimOcc':True,'occ_low':20,'occ_hi':48,
        #}},
    #{'name':'4x4_norm_v8_hinge','ws':'','pams':{'shape':(3,4,4) ,'channels_first':True,
        #     'CNN_layer_nodes':[8,4,4,4,2],
        #     'CNN_kernel_size':[3,3,3,3,3],
        #     'CNN_pool':[0,0,0,0,0],
        #     'loss':losses.hinge
        #}},

    for m in models:
        if options.quantize:
            m['pams'].update({
                'nBits_weight':nBits_weight,
                'nBits_input':nBits_input,
                'nBits_accum':nBits_accum,
                'nBits_encod': nBits_encod})
        if pam_updates:
            m['pams'].update(pam_updates)
            print ('updated parameters for model',m['name'])

    # compression algorithms, autoencoder and more traditional benchmarks
    algnames = ['ae','stc1','stc2','thr_lo','thr_hi']
    # metrics to compute on the validation dataset
    metrics = {'cross_corr'    :cross_corr,
               'SSD'      :ssd,
               'EMD'      :emd,
               'dMean':d_weighted_mean,
               'zero_frac':(lambda x,y: np.all(y==0)),}
    longMetric = {'cross_corr'    :'cross correlation',
                  'SSD'      :'sum of squared differences',
                  'EMD'      :'earth movers distance',
                  'dMean':'difference in energy-weighted mean',
                  'zero_frac':'zero fraction',}
    summary_entries=['name','en_pams','tot_pams']
    for algname in algnames:
        for mname in metrics:
            name = mname+"_"+algname
            summary_entries.append(mname+"_"+algname)
            summary_entries.append(mname+"_"+algname+"_err")
    summary = pd.DataFrame(columns=summary_entries)

    orig_dir = os.getcwd()
    if not os.path.exists(options.odir): os.mkdir(options.odir)
    os.chdir(options.odir)
    for model in models:
        model_name = model['name']
        if options.quantize: 
            bit_str = GetBitsString(model['pams']['nBits_input'], model['pams']['nBits_accum'],
                                    model['pams']['nBits_weight'], model['pams']['nBits_encod'],
                                    (model['pams']['nBits_dense'] if 'nBits_dense'  in model['pams'] else False),
                                    (model['pams']['nBits_conv'] if 'nBits_conv' in model['pams'] else False))
            model_name += "_" + bit_str
        if not os.path.exists(model_name): os.mkdir(model_name)
        os.chdir(model_name)

        if options.quantize:
            m = qDenseCNN(weights_f=model['ws'])
        else:
            m = denseCNN(weights_f=model['ws'])
        m.setpams(model['pams'])
        m.init()
        shaped_data                     = m.prepInput(normdata)
        val_input, train_input, val_ind = split(shaped_data)
        m_autoCNN , m_autoCNNen         = m.get_models()
        val_max = maxdata[val_ind]

        if model['ws']=='':
            if options.quickTrain: train_input = train_input[:5000]
            history = train(m_autoCNN,m_autoCNNen,train_input,val_input,name=model_name,n_epochs = options.epochs)
        else:
            save_models(m_autoCNN,model_name)

        summary_dict = {
            'name':model_name,
            'en_pams' : m_autoCNNen.count_params(),
            'tot_pams': m_autoCNN.count_params(),}

        input_Q,cnn_deQ ,cnn_enQ   = m.predict(val_input)
        
        ## csv files for RTL verification
        N_csv= (options.nCSV if options.nCSV>=0 else input_Q.shape[0]) # about 80k
        np.savetxt("verify_input.csv", input_Q[0:N_csv].reshape(N_csv,48), delimiter=",",fmt='%.12f')
        np.savetxt("verify_output.csv",cnn_enQ[0:N_csv].reshape(N_csv,m.pams['encoded_dim']), delimiter=",",fmt='%.12f')
        np.savetxt("verify_decoded.csv",cnn_deQ[0:N_csv].reshape(N_csv,48), delimiter=",",fmt='%.12f')
        
        stc1_Q = make_supercells(input_Q)
        stc2_Q = make_supercells(input_Q,shareQ=True)
        thr_lo_Q = threshold(input_Q,val_max,47) # 1.35 transverse MIPs
        thr_hi_Q = threshold(input_Q,val_max,69) # 2.0  transverse MIPs
        occupancy = np.count_nonzero(input_Q.reshape(len(input_Q),48),axis=1)
        alg_outs = {'ae' : cnn_deQ,
                    'stc1': stc1_Q,
                    'stc2': stc2_Q,
                    'thr_lo': thr_lo_Q,
                    'thr_hi': thr_hi_Q,
                }

        # to generate event displays
        Nevents = 8
        index = np.random.choice(input_Q.shape[0], Nevents, replace=False)

        # compute metrics for each alg
        for algname, alg_out in alg_outs.items():
            # charge fraction comparison
            if(not options.skipPlot): plotHist([input_Q.flatten(),alg_out.flatten()],
                                               algname+"_fracQ",xtitle="charge fraction",ytitle="Cells",
                                               stats=False,logy=True,leg=['input','output'])
            input_Q_abs = np.array([input_Q[i]*val_max[i] for i in range(0,len(input_Q))])
            alg_out_abs = np.array([alg_out[i]*val_max[i] for i in range(0,len(alg_out))])
            if(not options.skipPlot): plotHist([input_Q_abs.flatten(),alg_out_abs.flatten()],
                                               algname+"_absQ",xtitle="absolute charge",ytitle="Cells",
                                               stats=False,logy=True,leg=['input','output'])
            # event displays
            if(not options.skipPlot): visDisplays(index, input_Q, alg_out, (cnn_enQ if algname=='ae' else np.array([])), name=algname)
            for mname, metric in metrics.items():
                name = mname+"_"+algname
                vals = np.array([metric(input_Q[i],alg_out[i]) for i in range(0,len(input_Q))])
                vals = np.sort(vals)
                model[name]        = np.round(np.mean(vals), 3)
                model[name+'_err'] = np.round(np.std(vals), 3)
                summary_dict[name]        = model[name]
                summary_dict[name+'_err'] = model[name+'_err']
                if(not options.skipPlot) and (not('zero_frac' in mname)):
                    plotHist(vals,"hist_"+name,xtitle=longMetric[mname])
                    hi_index = (np.where(vals>np.quantile(vals,0.9)))[0]
                    lo_index = (np.where(vals<np.quantile(vals,0.2)))[0]
                    # visualize(input_Q,cnn_deQ,cnn_enQ,index,name=model_name)
                    if len(hi_index)>0:
                        hi_index = np.random.choice(hi_index, min(Nevents,len(hi_index)), replace=False)
                        visDisplays(hi_index, input_Q, alg_out, (cnn_enQ if algname=='ae' else np.array([])), name=algname)
                    if len(lo_index)>0:
                        lo_index = np.random.choice(lo_index, min(Nevents,len(lo_index)), replace=False)
                        visDisplays(lo_index, input_Q, alg_out, (cnn_enQ if algname=='ae' else np.array([])), name=algname)
                
        print('summary_dict',summary_dict)
        summary = summary.append(summary_dict, ignore_index=True)

        with open(model_name+"_pams.json",'w') as f:
            f.write(json.dumps(m.get_pams(),indent=4))
        
        os.chdir('../')
    os.chdir(orig_dir)
    print(summary)
    return summary    

if __name__== "__main__":

    parser = optparse.OptionParser()
    parser.add_option('-o',"--odir", type="string", default = 'CNN/',dest="odir", help="input TSG ntuple")
    parser.add_option('-i',"--inputFile", type="string", default = 'CALQ_output_10x.csv',dest="inputFile", help="input TSG ntuple")
    parser.add_option("--quantize", action='store_true', default = False,dest="quantize", help="Quantize the model with qKeras. Default precision is 16,6 for all values.")
    parser.add_option("--dryRun", action='store_true', default = False,dest="dryRun", help="dryRun")
    parser.add_option("--epochs", type='int', default = 100, dest="epochs", help="n epoch to train")
    parser.add_option("--skipPlot", action='store_true', default = False,dest="skipPlot", help="skip the plotting step")
    parser.add_option("--quickTrain", action='store_true', default = False,dest="quickTrain", help="train w only 5k events for testing purposes")
    parser.add_option("--nCSV", type='int', default = 50, dest="nCSV", help="n of validation events to write to csv")
    parser.add_option("--rescaleInputToMax", action='store_true', default = False,dest="rescaleInputToMax", help="recale the input images so the maximum deposit is 1. Else normalize")
    (options, args) = parser.parse_args()
    trainCNN(options,args)
