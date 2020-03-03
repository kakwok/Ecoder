from keras.layers import Input, Dense, Conv2D, MaxPooling2D, UpSampling2D, Flatten, Conv2DTranspose, Reshape, Activation
from keras.models import Model
from keras import backend as K
import qkeras as qkr
from qkeras.qlayers import QConv2D,QActivation,QDense
import numpy as np
import json


class qDenseCNN:
    def __init__(self, name='', weights_f=''):
        self.name = name
        self.pams = {
            'CNN_layer_nodes': [8],  # n_filters
            'CNN_kernel_size': [3],
            'CNN_pool': [False],
            'Dense_layer_nodes': [],  # does not include encoded layer
            'encoded_dim': 12,
            'shape': (1, 4, 4),
            'channels_first': False,
            'arrange': [],
            'arrMask': [],
            'n_copy': 0,  # no. of copy for hi occ datasets
            'loss': ''
        }

        self.weights_f = weights_f

    def setpams(self, in_pams):
        for k, v in in_pams.items():
            self.pams[k] = v

    def shuffle(self, arr):
        order = np.arange(48)
        np.random.shuffle(order)
        return arr[:, order]

    def cloneInput(self, input_q, n_copy, occ_low, occ_hi):
        shape = self.pams['shape']
        nonzeroQs = np.count_nonzero(input_q.reshape(len(input_q), 48), axis=1)
        selection = np.logical_and(nonzeroQs <= occ_hi, nonzeroQs > occ_low)
        occ_q = input_q[selection]
        occ_q_flat = occ_q.reshape(len(occ_q), 48)
        self.pams['cloned_fraction'] = len(occ_q) / len(input_q)
        for i in range(0, n_copy):
            clone = self.shuffle(occ_q_flat)
            clone = clone.reshape(len(clone), shape[0], shape[1], shape[2])
            input_q = np.concatenate([input_q, clone])
        return input_q

    def prepInput(self, normData):
        shape = self.pams['shape']

        if len(self.pams['arrange']) > 0:
            arrange = self.pams['arrange']
            inputdata = normData[:, arrange]
        else:
            inputdata = normData
        if len(self.pams['arrMask']) > 0:
            arrMask = self.pams['arrMask']
            inputdata[:, arrMask == 0] = 0  # zeros out repeated entries

        shaped_data = inputdata.reshape(len(inputdata), shape[0], shape[1], shape[2])

        if self.pams['n_copy'] > 0:
            n_copy = self.pams['n_copy']
            occ_low = self.pams['occ_low']
            occ_hi = self.pams['occ_hi']
            shaped_data = self.cloneInput(shaped_data, n_copy, occ_low, occ_hi)
        # if self.pams['skimOcc']:
        #  occ_low = self.pams['occ_low']
        #  occ_hi = self.pams['occ_hi']
        #  nonzeroQs = np.count_nonzero(shaped_data.reshape(len(shaped_data),48),axis=1)
        #  selection = np.logical_and(nonzeroQs<=occ_hi,nonzeroQs>occ_low)
        #  shaped_data     = shaped_data[selection]

        return shaped_data

    def weightedMSE(self, y_true, y_pred):
        y_true = K.cast(y_true, y_pred.dtype)
        loss = K.mean(K.square(y_true - y_pred) * K.maximum(y_pred, y_true), axis=(-1))
        return loss

    def init(self, printSummary=True): # keep_negitive = 0 on inputs, otherwise for weights keep default (=1)
        encoded_dim = self.pams['encoded_dim']

        CNN_layer_nodes = self.pams['CNN_layer_nodes']
        CNN_kernel_size = self.pams['CNN_kernel_size']
        CNN_pool = self.pams['CNN_pool']
        Dense_layer_nodes = self.pams['Dense_layer_nodes']  # does not include encoded layer
        channels_first = self.pams['channels_first']

        inputs = Input(shape=self.pams['shape'])  # adapt this if using `channels_first` image data format
        qbits_param = self.pams['qbits'] #quantized bits string, (bits=n,integer=m,keep_negitive=1), weights should *always* be signed
        qbits = {
            "kernel_quantizer": "quantized_bits" + qbits_param,
            "bias_quantizer": "quantized_bits" + qbits_param
        }
        activation_bits =  self.pams['act_bits']
        en_qdict = {}
        de_qdict = {}
        x = inputs

        for i, n_nodes in enumerate(CNN_layer_nodes):
            if channels_first:
                x = Conv2D(n_nodes, CNN_kernel_size[i], activation='relu', padding='same',
                           data_format='channels_first', name="conv2d_"+str(i)+"_m")(x)
            else:
                x = Conv2D(n_nodes, CNN_kernel_size[i], activation='relu', padding='same', name="conv2d_"+str(i)+"_m")(x)
            en_qdict.update({"conv2d_"+str(i)+"_m":qbits})
            if CNN_pool[i]:
                if channels_first:
                    x = MaxPooling2D((2, 2), padding='same', data_format='channels_first', name="mp_"+str(i))(x)
                else:
                    x = MaxPooling2D((2, 2), padding='same', name="mp_"+str(i))(x)
                en_qdict.update({"mp_" + str(i): qbits})

        shape = K.int_shape(x)

        x = Flatten(name="flatten")(x)
        en_qdict.update({"flatten": qbits})

        # encoder dense nodes
        for i, n_nodes in enumerate(Dense_layer_nodes):
            x = Dense(n_nodes, activation='relu', name="en_dense_"+str(i))(x)
            en_qdict.update({"en_dense_" + str(i): qbits})

        encodedLayer = Dense(encoded_dim, activation='relu', name='encoded_vector')(x)
        en_qdict.update({"encoded_vector": qbits})

        # Instantiate Encoder Model
        self.encoder = Model(inputs, encodedLayer, name='encoder')
        self.qencoder, _ = qkr.model_quantize(self.encoder,en_qdict,activation_bits)
        if printSummary:
            self.encoder.summary()
            self.qencoder.summary()

        encoded_inputs = Input(shape=(encoded_dim,), name='decoder_input')
        x = encoded_inputs

        # decoder dense nodes
        for i, n_nodes in enumerate(Dense_layer_nodes):
            x = Dense(n_nodes, activation='relu', name="de_dense_"+str(i))(x)

        x = Dense(shape[1] * shape[2] * shape[3], activation='relu', name='de_dense_final')(x)
        x = Reshape((shape[1], shape[2], shape[3]),name="de_reshape")(x)

        for i, n_nodes in enumerate(CNN_layer_nodes):

            if CNN_pool[i]:
                if channels_first:
                    x = UpSampling2D((2, 2), data_format='channels_first', name="up_"+str(i))(x)
                else:
                    x = UpSampling2D((2, 2), name="up_"+str(i))(x)

            if channels_first:
                x = Conv2DTranspose(n_nodes, CNN_kernel_size[i], activation='relu', padding='same',
                                    data_format='channels_first', name="conv2D_t_"+str(i))(x)
            else:
                x = Conv2DTranspose(n_nodes, CNN_kernel_size[i], activation='relu', padding='same',
                                    name="conv2D_t_"+str(i))(x)

        if channels_first:
            # shape[0] will be # of channel
            x = Conv2DTranspose(filters=self.pams['shape'][0], kernel_size=CNN_kernel_size[0], padding='same',
                                data_format='channels_first', name="conv2d_t_final")(x)

        else:
            x = Conv2DTranspose(filters=self.pams['shape'][2], kernel_size=CNN_kernel_size[0], padding='same',
                                name="conv2d_t_final")(x)

        outputs = Activation('sigmoid', name='decoder_output')(x)

        self.decoder = Model(encoded_inputs, outputs, name='decoder')
        if printSummary:
            self.decoder.summary()

        self.autoencoder = Model(inputs, self.decoder(self.encoder(inputs)), name='autoencoder')
        auto_dict = en_qdict
        self.qautoencoder, _ = qkr.model_quantize(self.autoencoder, auto_dict, activation_bits)
        if printSummary:
            self.autoencoder.summary()
            self.qautoencoder.summary()

        if self.pams['loss'] == "weightedMSE":
            self.autoencoder.compile(loss=self.weightedMSE, optimizer='adam')
            self.encoder.compile(loss=self.weightedMSE, optimizer='adam')
            #quantized models
            self.qautoencoder.compile(loss=self.weightedMSE, optimizer='adam')
            self.qencoder.compile(loss=self.weightedMSE, optimizer='adam')
        elif self.pams['loss'] != '':
            self.autoencoder.compile(loss=self.pams['loss'], optimizer='adam')
            self.encoder.compile(loss=self.pams['loss'], optimizer='adam')
            #quantized models
            self.qautoencoder.compile(loss=self.pams['loss'], optimizer='adam')
            self.qencoder.compile(loss=self.pams['loss'], optimizer='adam')
        else:
            self.autoencoder.compile(loss='mse', optimizer='adam')
            self.encoder.compile(loss='mse', optimizer='adam')
            #quantized models
            self.qautoencoder.compile(loss='mse', optimizer='adam')
            self.qencoder.compile(loss='mse', optimizer='adam')

        CNN_layers = ''
        if len(CNN_layer_nodes) > 0:
            CNN_layers += '_Conv'
            for i, n in enumerate(CNN_layer_nodes):
                CNN_layers += f'_{n}x{CNN_kernel_size[i]}'
                if CNN_pool[i]:
                    CNN_layers += 'pooled'
        Dense_layers = ''
        if len(Dense_layer_nodes) > 0:
            Dense_layers += '_Dense'
            for n in Dense_layer_nodes:
                Dense_layers += f'_{n}'

        self.name = f'Autoencoded{CNN_layers}{Dense_layers}_Encoded_{encoded_dim}'

        if not self.weights_f == '':
            self.autoencoder.load_weights(self.weights_f)

    def get_models(self):
        return self.autoencoder, self.encoder
    def get_q_models(self):
        return self.qautoencoder, self.qencoder

    def predict(self, x):
        decoded_Q = self.autoencoder.predict(x)
        encoded_Q = self.encoder.predict(x)
        s = self.pams['shape']
        if self.pams['channels_first']:
            shaped_x = np.reshape(x, (len(x), s[0] * s[1], s[2]))
            decoded_Q = np.reshape(decoded_Q, (len(decoded_Q), s[0] * s[1], s[2]))
            encoded_Q = np.reshape(encoded_Q, (len(encoded_Q), self.pams['encoded_dim'], 1))
        else:
            shaped_x = np.reshape(x, (len(x), s[2] * s[1], s[0]))
            decoded_Q = np.reshape(decoded_Q, (len(decoded_Q), s[2] * s[1], s[0]))
            encoded_Q = np.reshape(encoded_Q, (len(encoded_Q), self.pams['encoded_dim'], 1))
        return shaped_x, decoded_Q, encoded_Q

    def q_predict(self, x):
        decoded_Q = self.qautoencoder.predict(x)
        encoded_Q = self.qencoder.predict(x)
        s = self.pams['shape']
        if self.pams['channels_first']:
            shaped_x = np.reshape(x, (len(x), s[0] * s[1], s[2]))
            decoded_Q = np.reshape(decoded_Q, (len(decoded_Q), s[0] * s[1], s[2]))
            encoded_Q = np.reshape(encoded_Q, (len(encoded_Q), self.pams['encoded_dim'], 1))
        else:
            shaped_x = np.reshape(x, (len(x), s[2] * s[1], s[0]))
            decoded_Q = np.reshape(decoded_Q, (len(decoded_Q), s[2] * s[1], s[0]))
            encoded_Q = np.reshape(encoded_Q, (len(encoded_Q), self.pams['encoded_dim'], 1))
        return shaped_x, decoded_Q, encoded_Q

    def summary(self):
        self.encoder.summary()
        self.decoder.summary()
        self.autoencoder.summary()

    def q_summary(self):
        self.qencoder.summary()
        self.decoder.summary()
        self.qautoencoder.summary()

    ##get pams for writing json
    def get_pams(self):
        jsonpams = {}
        for k, v in self.pams.items():
            if type(v) == type(np.array([])):
                jsonpams[k] = v.tolist()
            else:
                jsonpams[k] = v
        return jsonpams
